"""
深度论文分析服务
处理论文深度分析的业务逻辑
"""
import os
import sys
import threading
import time
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

# 添加 HomeSystem 模块路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from database import PaperService

# 导入ArXiv相关模块用于论文下载和OCR处理
from HomeSystem.utility.arxiv.arxiv import ArxivData

logger = logging.getLogger(__name__)


class DeepAnalysisService:
    """深度论文分析服务类"""
    
    def __init__(self, paper_service: PaperService, redis_client=None):
        self.paper_service = paper_service
        self.analysis_threads = {}  # 存储正在进行的分析线程
        self.redis_client = redis_client  # Redis客户端用于读取配置
        
        # 默认配置
        self.default_config = {
            'analysis_model': 'deepseek.DeepSeek_V3',
            'vision_model': 'ollama.Qwen2_5_VL_7B',
            'timeout': 600  # 10分钟超时
        }
    
    def load_config(self) -> Dict[str, Any]:
        """
        从Redis加载配置，如果不存在则使用默认配置
        
        Returns:
            Dict: 配置字典
        """
        config = self.default_config.copy()
        
        if self.redis_client:
            try:
                config_key = "analysis_config:global"
                saved_config = self.redis_client.get(config_key)
                if saved_config:
                    import json
                    saved_data = json.loads(saved_config)
                    config.update(saved_data)
                    logger.info(f"从Redis加载配置: {config}")
                else:
                    logger.info("Redis中未找到配置，使用默认配置")
            except Exception as e:
                logger.warning(f"从Redis加载配置失败，使用默认配置: {e}")
        else:
            logger.info("Redis不可用，使用默认配置")
        
        return config
    
    def start_analysis(self, arxiv_id: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        启动论文深度分析
        
        Args:
            arxiv_id: ArXiv论文ID
            config: 分析配置（可选）
            
        Returns:
            Dict: 操作结果
        """
        try:
            logger.info(f"🚀 开始启动深度分析 - ArXiv ID: {arxiv_id}")
            
            # 检查论文是否存在
            paper = self.paper_service.get_paper_detail(arxiv_id)
            if not paper:
                logger.error(f"❌ 论文不存在: {arxiv_id}")
                return {
                    'success': False,
                    'error': f'论文 {arxiv_id} 不存在'
                }
            
            logger.info(f"✅ 论文存在检查通过: {arxiv_id}")
            
            # 检查是否已在分析中
            if arxiv_id in self.analysis_threads:
                thread = self.analysis_threads[arxiv_id]
                if thread.is_alive():
                    logger.warning(f"⚠️ 论文已在分析中: {arxiv_id}")
                    return {
                        'success': False,
                        'error': '该论文正在分析中，请稍后'
                    }
                else:
                    # 清理已完成的线程
                    del self.analysis_threads[arxiv_id]
                    logger.info(f"🧹 清理了已完成的线程: {arxiv_id}")
            
            # 更新分析状态为处理中
            self.paper_service.update_analysis_status(arxiv_id, 'processing')
            
            # 加载当前配置
            current_config = self.load_config()
            
            # 合并配置（用户传入的配置优先）
            analysis_config = {**current_config, **(config or {})}
            
            # 创建并启动分析线程
            thread = threading.Thread(
                target=self._run_analysis,
                args=(arxiv_id, paper, analysis_config),
                daemon=True
            )
            thread.start()
            
            # 保存线程引用
            self.analysis_threads[arxiv_id] = thread
            
            logger.info(f"Started deep analysis for paper {arxiv_id}")
            
            return {
                'success': True,
                'message': '深度分析已启动',
                'status': 'processing'
            }
            
        except Exception as e:
            logger.error(f"Failed to start analysis for {arxiv_id}: {e}")
            # 更新状态为失败
            try:
                self.paper_service.update_analysis_status(arxiv_id, 'failed')
            except:
                pass
            
            return {
                'success': False,
                'error': f'启动分析失败: {str(e)}'
            }
    
    def _run_analysis(self, arxiv_id: str, paper: Dict[str, Any], config: Dict[str, Any]):
        """
        执行论文分析（在后台线程中运行）
        
        Args:
            arxiv_id: ArXiv论文ID
            paper: 论文信息字典
            config: 分析配置
        """
        try:
            logger.info(f"🚀 开始执行深度分析 - ArXiv ID: {arxiv_id}")
            
            # 第一步：准备论文数据和文件夹
            paper_folder = self._prepare_paper_folder(arxiv_id, paper)
            if not paper_folder:
                logger.error(f"❌ 论文文件夹准备失败: {arxiv_id}")
                self.paper_service.update_analysis_status(arxiv_id, 'failed')
                return
                
            logger.info(f"✅ 论文文件夹准备完成: {paper_folder}")
            
            # 第二步：下载论文PDF（如果尚未下载）
            success = self._download_paper_pdf(arxiv_id, paper, paper_folder)
            if not success:
                logger.error(f"❌ 论文PDF下载失败: {arxiv_id}")
                self.paper_service.update_analysis_status(arxiv_id, 'failed')
                return
                
            logger.info(f"✅ 论文PDF下载完成: {arxiv_id}")
            
            # 第三步：执行OCR处理（如果尚未处理）
            success = self._perform_paper_ocr(arxiv_id, paper_folder)
            if not success:
                logger.error(f"❌ 论文OCR处理失败: {arxiv_id}")
                self.paper_service.update_analysis_status(arxiv_id, 'failed')
                return
                
            logger.info(f"✅ 论文OCR处理完成: {arxiv_id}")
            
            # 第四步：执行深度分析
            success = self._execute_deep_analysis(arxiv_id, paper_folder, config)
            if not success:
                logger.error(f"❌ 深度分析执行失败: {arxiv_id}")
                self.paper_service.update_analysis_status(arxiv_id, 'failed')
                return
                
            logger.info(f"✅ 深度分析执行完成: {arxiv_id}")
            
        except Exception as e:
            logger.error(f"💥 分析过程失败 {arxiv_id}: {e}")
            # 更新状态为失败
            try:
                self.paper_service.update_analysis_status(arxiv_id, 'failed')
            except:
                pass
        finally:
            # 清理线程引用
            if arxiv_id in self.analysis_threads:
                del self.analysis_threads[arxiv_id]
    
    def _prepare_paper_folder(self, arxiv_id: str, paper: Dict[str, Any]) -> Optional[str]:
        """
        准备论文分析文件夹
        
        Args:
            arxiv_id: ArXiv论文ID
            paper: 论文信息字典
            
        Returns:
            str: 论文文件夹路径，失败返回None
        """
        try:
            # 标准化论文文件夹路径
            paper_folder = f"/mnt/nfs_share/code/homesystem/data/paper_analyze/{arxiv_id}"
            paper_folder_path = Path(paper_folder)
            
            # 创建文件夹（如果不存在）
            paper_folder_path.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"📁 论文文件夹已准备: {paper_folder}")
            return paper_folder
            
        except Exception as e:
            logger.error(f"❌ 准备论文文件夹失败 {arxiv_id}: {e}")
            return None
    
    def _download_paper_pdf(self, arxiv_id: str, paper: Dict[str, Any], paper_folder: str) -> bool:
        """
        下载论文PDF文件
        
        Args:
            arxiv_id: ArXiv论文ID
            paper: 论文信息字典
            paper_folder: 论文文件夹路径
            
        Returns:
            bool: 下载是否成功
        """
        try:
            # 检查PDF是否已存在
            pdf_path = os.path.join(paper_folder, f"{arxiv_id}.pdf")
            if os.path.exists(pdf_path):
                logger.info(f"📄 PDF文件已存在，跳过下载: {pdf_path}")
                return True
            
            # 构造PDF下载URL
            pdf_url = paper.get('pdf_url')
            if not pdf_url:
                # 构造标准的ArXiv PDF URL
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                
            logger.info(f"📥 开始下载PDF: {pdf_url}")
            
            # 创建ArxivData实例并下载PDF
            arxiv_data = ArxivData({
                'title': paper.get('title', ''),
                'link': f"https://arxiv.org/abs/{arxiv_id}",
                'snippet': paper.get('abstract', ''),
                'categories': paper.get('categories', ''),
                'arxiv_id': arxiv_id
            })
            
            # 下载PDF到指定路径（传递目录路径，让downloadPdf自行处理文件名）
            arxiv_data.downloadPdf(save_path=paper_folder)
            
            # 检查是否下载成功（downloadPdf会根据标题创建文件名）
            # 我们需要找到实际创建的PDF文件
            pdf_files = [f for f in os.listdir(paper_folder) if f.endswith('.pdf')]
            if pdf_files:
                # 重命名为标准格式
                actual_pdf_path = os.path.join(paper_folder, pdf_files[0])
                if actual_pdf_path != pdf_path and os.path.exists(actual_pdf_path):
                    os.rename(actual_pdf_path, pdf_path)
                    logger.info(f"📁 PDF重命名为标准格式: {pdf_path}")
            else:
                logger.error(f"❌ 未找到下载的PDF文件")
                return False
            
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                logger.info(f"✅ PDF下载成功: {pdf_path}")
                return True
            else:
                logger.error(f"❌ PDF下载失败，文件不存在或为空: {pdf_path}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 下载PDF失败 {arxiv_id}: {e}")
            return False
    
    def _perform_paper_ocr(self, arxiv_id: str, paper_folder: str) -> bool:
        """
        执行论文OCR处理
        
        Args:
            arxiv_id: ArXiv论文ID
            paper_folder: 论文文件夹路径
            
        Returns:
            bool: OCR处理是否成功
        """
        try:
            # 检查OCR结果是否已存在
            ocr_file = os.path.join(paper_folder, f"{arxiv_id}_paddleocr.md")
            if os.path.exists(ocr_file):
                logger.info(f"📝 OCR文件已存在，跳过处理: {ocr_file}")
                return True
            
            # 检查PDF文件
            pdf_path = os.path.join(paper_folder, f"{arxiv_id}.pdf")
            if not os.path.exists(pdf_path):
                logger.error(f"❌ PDF文件不存在: {pdf_path}")
                return False
            
            logger.info(f"🔍 开始OCR处理: {pdf_path}")
            
            # 创建ArxivData实例并执行OCR
            arxiv_data = ArxivData({
                'title': '',
                'link': f"https://arxiv.org/abs/{arxiv_id}",
                'snippet': '',
                'categories': '',
                'arxiv_id': arxiv_id
            })
            
            # 从文件加载PDF
            with open(pdf_path, 'rb') as f:
                arxiv_data.pdf = f.read()
            
            # 执行PaddleOCR处理
            ocr_result, status_info = arxiv_data.performOCR(
                use_paddleocr=True, 
                auto_save=True,
                save_path=paper_folder
            )
            
            if ocr_result and len(ocr_result.strip()) > 0:
                logger.info(f"✅ OCR处理成功，生成 {len(ocr_result)} 字符: {arxiv_id}")
                return True
            else:
                logger.error(f"❌ OCR处理失败，未生成有效内容: {arxiv_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ OCR处理失败 {arxiv_id}: {e}")
            return False
    
    def _execute_deep_analysis(self, arxiv_id: str, paper_folder: str, config: Dict[str, Any]) -> bool:
        """
        执行深度分析
        
        Args:
            arxiv_id: ArXiv论文ID
            paper_folder: 论文文件夹路径
            config: 分析配置
            
        Returns:
            bool: 分析是否成功
        """
        try:
            logger.info(f"🤖 开始深度分析: {arxiv_id}")
            
            # 动态导入深度分析智能体（延迟导入避免启动时的兼容性问题）
            try:
                from HomeSystem.graph.deep_paper_analysis_agent import create_deep_paper_analysis_agent
                logger.info("✅ Successfully imported deep paper analysis agent")
            except Exception as import_error:
                logger.error(f"❌ Failed to import deep paper analysis agent: {import_error}")
                return False
            
            # 创建深度分析智能体
            logger.info("🤖 Creating deep paper analysis agent...")
            agent = create_deep_paper_analysis_agent(
                analysis_model=config['analysis_model'],
                vision_model=config['vision_model']
            )
            logger.info("✅ Deep paper analysis agent created successfully")
            
            # 执行分析
            analysis_result, report_content = agent.analyze_and_generate_report(
                folder_path=paper_folder,
                thread_id=f"web_analysis_{arxiv_id}_{int(time.time())}"
            )
            
            # 检查分析是否成功
            if 'error' in analysis_result:
                logger.error(f"Analysis failed for {arxiv_id}: {analysis_result['error']}")
                return False
            
            # 处理分析结果
            if analysis_result.get('analysis_result') or report_content:
                # 使用分析结果或报告内容
                final_content = analysis_result.get('analysis_result') or report_content
                
                # 处理图片路径
                processed_content = self._process_image_paths(final_content, arxiv_id)
                
                # 保存分析结果
                self.paper_service.save_analysis_result(arxiv_id, processed_content)
                
                # 保存到文件
                analysis_file = os.path.join(paper_folder, f"{arxiv_id}_analysis.md")
                with open(analysis_file, 'w', encoding='utf-8') as f:
                    f.write(processed_content)
                
                logger.info(f"Analysis completed for {arxiv_id}, saved {len(processed_content)} characters")
                
                # 更新状态为完成
                self.paper_service.update_analysis_status(arxiv_id, 'completed')
                return True
            else:
                logger.warning(f"No analysis result generated for {arxiv_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 执行深度分析失败 {arxiv_id}: {e}")
            return False
    
    def _process_image_paths(self, content: str, arxiv_id: str) -> str:
        """
        处理Markdown内容中的图片路径，将相对路径转换为可访问的URL路径
        
        Args:
            content: 原始Markdown内容
            arxiv_id: ArXiv论文ID
            
        Returns:
            str: 处理后的Markdown内容
        """
        try:
            # 使用正则表达式匹配Markdown图片语法
            img_pattern = r'!\[(.*?)\]\((imgs/[^)]+)\)'
            
            def replace_image_path(match):
                alt_text = match.group(1)
                relative_path = match.group(2)
                # 转换为Flask可访问的URL路径
                new_path = f"/paper/{arxiv_id}/analysis_images/{relative_path.replace('imgs/', '')}"
                return f"![{alt_text}]({new_path})"
            
            # 替换所有图片路径
            processed_content = re.sub(img_pattern, replace_image_path, content)
            
            logger.info(f"Processed {len(re.findall(img_pattern, content))} image paths for {arxiv_id}")
            
            return processed_content
            
        except Exception as e:
            logger.error(f"Failed to process image paths for {arxiv_id}: {e}")
            return content
    
    def get_analysis_status(self, arxiv_id: str) -> Dict[str, Any]:
        """
        获取分析状态
        
        Args:
            arxiv_id: ArXiv论文ID
            
        Returns:
            Dict: 状态信息
        """
        try:
            # 从数据库获取状态
            status_info = self.paper_service.get_analysis_status(arxiv_id)
            
            if not status_info:
                return {
                    'success': True,
                    'status': 'not_started',
                    'message': '尚未开始分析'
                }
            
            # 检查是否有正在运行的线程
            if arxiv_id in self.analysis_threads:
                thread = self.analysis_threads[arxiv_id]
                if thread.is_alive():
                    status_info['is_running'] = True
                else:
                    # 清理已完成的线程
                    del self.analysis_threads[arxiv_id]
                    status_info['is_running'] = False
            else:
                status_info['is_running'] = False
            
            return {
                'success': True,
                **status_info
            }
            
        except Exception as e:
            logger.error(f"Failed to get analysis status for {arxiv_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_analysis_result(self, arxiv_id: str) -> Dict[str, Any]:
        """
        获取分析结果
        
        Args:
            arxiv_id: ArXiv论文ID
            
        Returns:
            Dict: 分析结果
        """
        try:
            result = self.paper_service.get_analysis_result(arxiv_id)
            
            if not result:
                return {
                    'success': False,
                    'error': '分析结果不存在'
                }
            
            return {
                'success': True,
                **result
            }
            
        except Exception as e:
            logger.error(f"Failed to get analysis result for {arxiv_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def cancel_analysis(self, arxiv_id: str) -> Dict[str, Any]:
        """
        取消正在进行的分析
        
        Args:
            arxiv_id: ArXiv论文ID
            
        Returns:
            Dict: 操作结果
        """
        try:
            if arxiv_id not in self.analysis_threads:
                return {
                    'success': False,
                    'error': '没有正在进行的分析'
                }
            
            thread = self.analysis_threads[arxiv_id]
            if not thread.is_alive():
                del self.analysis_threads[arxiv_id]
                return {
                    'success': False,
                    'error': '分析已完成或已停止'
                }
            
            # 注意：Python线程无法强制停止，这里只能标记状态
            # 实际的线程仍会继续运行直到自然结束
            del self.analysis_threads[arxiv_id]
            
            # 更新数据库状态
            self.paper_service.update_analysis_status(arxiv_id, 'cancelled')
            
            logger.info(f"Analysis cancelled for {arxiv_id}")
            
            return {
                'success': True,
                'message': '分析已取消'
            }
            
        except Exception as e:
            logger.error(f"Failed to cancel analysis for {arxiv_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def cleanup_completed_threads(self):
        """清理已完成的分析线程"""
        completed_threads = []
        
        for arxiv_id, thread in self.analysis_threads.items():
            if not thread.is_alive():
                completed_threads.append(arxiv_id)
        
        for arxiv_id in completed_threads:
            del self.analysis_threads[arxiv_id]
        
        if completed_threads:
            logger.info(f"Cleaned up {len(completed_threads)} completed analysis threads")
    
    def get_active_analyses(self) -> Dict[str, Any]:
        """
        获取所有活跃的分析任务
        
        Returns:
            Dict: 活跃任务信息
        """
        try:
            self.cleanup_completed_threads()
            
            active_analyses = []
            for arxiv_id, thread in self.analysis_threads.items():
                if thread.is_alive():
                    status_info = self.paper_service.get_analysis_status(arxiv_id)
                    if status_info:
                        active_analyses.append({
                            'arxiv_id': arxiv_id,
                            **status_info
                        })
            
            return {
                'success': True,
                'active_count': len(active_analyses),
                'analyses': active_analyses
            }
            
        except Exception as e:
            logger.error(f"Failed to get active analyses: {e}")
            return {
                'success': False,
                'error': str(e)
            }