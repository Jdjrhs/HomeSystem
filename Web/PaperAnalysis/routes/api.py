"""
统一API路由 - 整合两个应用的API接口
提供RESTful API接口用于前端调用和第三方集成
"""
from flask import Blueprint, request, jsonify, send_file
from services.task_service import paper_gather_service
from services.paper_gather_service import paper_data_service
from services.paper_explore_service import PaperService, DifyService
from HomeSystem.integrations.paper_analysis.analysis_service import PaperAnalysisService
import logging
import os
import sys
import json
import tempfile
import zipfile
import re
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 定义项目根目录
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')
sys.path.append(PROJECT_ROOT)

api_bp = Blueprint('api', __name__, url_prefix='/api')

# 初始化服务
paper_explore_service = PaperService()
dify_service = DifyService()

# 初始化Redis连接
try:
    import redis
    from config import REDIS_CONFIG
    redis_client = redis.Redis(
        host=REDIS_CONFIG['host'],
        port=REDIS_CONFIG['port'],
        db=REDIS_CONFIG['db'],
        decode_responses=True
    )
    redis_client.ping()
except Exception as e:
    logger.warning(f"API模块Redis连接失败: {e}")
    redis_client = None

# 初始化分析服务
paper_analysis_service = PaperAnalysisService()

# 分析服务适配器类 - 桥接PaperAnalysisService和Web API接口
class AnalysisServiceAdapter:
    """Web API分析服务适配器"""
    
    def __init__(self, paper_service: PaperService, redis_client=None):
        self.paper_service = paper_service
        self.redis_client = redis_client
        self.analysis_threads = {}  # 存储正在进行的分析线程
        
        # 默认配置
        self.default_config = {
            'analysis_model': 'deepseek.DeepSeek_V3',
            'vision_model': 'ollama.Qwen2_5_VL_7B', 
            'timeout': 600
        }
    
    def load_config(self) -> Dict[str, Any]:
        """从Redis加载配置，如果不存在则使用默认配置"""
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
            except Exception as e:
                logger.warning(f"从Redis加载配置失败，使用默认配置: {e}")
        
        return config
    
    def start_analysis(self, arxiv_id: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """启动论文深度分析"""
        try:
            import threading
            from pathlib import Path
            
            logger.info(f"🚀 开始启动深度分析 - ArXiv ID: {arxiv_id}")
            
            # 检查论文是否存在
            paper = self.paper_service.get_paper_detail(arxiv_id)
            if not paper:
                logger.error(f"❌ 论文不存在: {arxiv_id}")
                return {
                    'success': False,
                    'error': f'论文 {arxiv_id} 不存在'
                }
            
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
                    del self.analysis_threads[arxiv_id]
            
            # 更新分析状态为处理中
            self.paper_service.update_analysis_status(arxiv_id, 'processing')
            
            # 加载当前配置
            current_config = self.load_config()
            analysis_config = {**current_config, **(config or {})}
            
            # 创建并启动分析线程
            thread = threading.Thread(
                target=self._run_analysis,
                args=(arxiv_id, paper, analysis_config),
                daemon=True
            )
            thread.start()
            self.analysis_threads[arxiv_id] = thread
            
            logger.info(f"Started deep analysis for paper {arxiv_id}")
            
            return {
                'success': True,
                'message': '深度分析已启动',
                'status': 'processing'
            }
            
        except Exception as e:
            logger.error(f"Failed to start analysis for {arxiv_id}: {e}")
            try:
                self.paper_service.update_analysis_status(arxiv_id, 'failed')
            except:
                pass
            
            return {
                'success': False,
                'error': f'启动分析失败: {str(e)}'
            }
    
    def _run_analysis(self, arxiv_id: str, paper: Dict[str, Any], config: Dict[str, Any]):
        """执行论文分析（在后台线程中运行）"""
        try:
            from pathlib import Path
            import re
            
            logger.info(f"🚀 开始执行深度分析 - ArXiv ID: {arxiv_id}")
            
            # 创建分析服务实例
            analysis_service = PaperAnalysisService(default_config=config)
            
            # 计算论文文件夹路径
            project_root = Path(__file__).parent.parent.parent.parent
            paper_folder_path = str(project_root / "data" / "paper_analyze" / arxiv_id)
            
            # 准备论文数据（用于PDF下载）
            paper_data = {
                'title': paper.get('title', ''),
                'link': f"https://arxiv.org/abs/{arxiv_id}",
                'snippet': paper.get('abstract', ''),
                'categories': paper.get('categories', ''),
                'arxiv_id': arxiv_id
            }
            
            # 执行完整的深度分析流程
            result = analysis_service.perform_deep_analysis(
                arxiv_id=arxiv_id,
                paper_folder_path=paper_folder_path,
                config=config,
                paper_data=paper_data
            )
            
            if result['success']:
                # 使用Web应用特有的图片路径处理
                processed_content = self._process_image_paths(
                    result['analysis_result'], 
                    arxiv_id
                )
                
                # 保存分析结果到数据库
                self.paper_service.save_analysis_result(arxiv_id, processed_content)
                
                # 重新保存处理后的内容到文件
                with open(result['analysis_file_path'], 'w', encoding='utf-8') as f:
                    f.write(processed_content)
                
                logger.info(f"Analysis completed for {arxiv_id}, saved {len(processed_content)} characters")
                self.paper_service.update_analysis_status(arxiv_id, 'completed')
            else:
                logger.error(f"❌ 深度分析失败: {arxiv_id}: {result.get('error', '未知错误')}")
                self.paper_service.update_analysis_status(arxiv_id, 'failed')
            
        except Exception as e:
            logger.error(f"💥 分析过程失败 {arxiv_id}: {e}")
            try:
                self.paper_service.update_analysis_status(arxiv_id, 'failed')
            except:
                pass
        finally:
            if arxiv_id in self.analysis_threads:
                del self.analysis_threads[arxiv_id]
    
    def _process_image_paths(self, content: str, arxiv_id: str) -> str:
        """处理Markdown内容中的图片路径，将相对路径转换为可访问的URL路径"""
        try:
            logger.info(f"🖼️ Starting image path processing for {arxiv_id}")
            
            # 匹配 ![alt](imgs/filename) 格式
            img_pattern = r'!\[([^\]]*)\]\((imgs/[^)]+)\)'
            
            def replace_image_path(match):
                alt_text = match.group(1)
                relative_path = match.group(2)
                filename = relative_path.replace('imgs/', '')
                new_path = f"/paper/{arxiv_id}/analysis_images/{filename}"
                logger.debug(f"  📸 Converting: {relative_path} → {new_path}")
                return f"![{alt_text}]({new_path})"
            
            # 统计和替换
            original_matches = re.findall(img_pattern, content)
            logger.info(f"  📊 Found {len(original_matches)} image references for {arxiv_id}")
            
            processed_content = re.sub(img_pattern, replace_image_path, content)
            
            # 验证处理结果
            processed_matches = re.findall(r'!\[([^\]]*)\]\((/paper/[^)]+)\)', processed_content)
            logger.info(f"  ✅ Successfully processed {len(processed_matches)} image paths for {arxiv_id}")
            
            return processed_content
            
        except Exception as e:
            logger.error(f"❌ Failed to process image paths for {arxiv_id}: {e}")
            return content
    
    def get_analysis_status(self, arxiv_id: str) -> Dict[str, Any]:
        """获取分析状态"""
        try:
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
        """获取分析结果"""
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

# 创建适配器实例
analysis_service = AnalysisServiceAdapter(paper_explore_service, redis_client)


# === 论文收集相关API (来自PaperGather) ===

@api_bp.route('/collect/models')
def get_available_models():
    """获取可用的LLM模型"""
    try:
        models = paper_gather_service.get_available_models()
        return jsonify({
            'success': True,
            'models': models
        })
    except Exception as e:
        logger.error(f"获取模型列表失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/collect/search_modes')
def get_search_modes():
    """获取可用的搜索模式"""
    try:
        modes = paper_gather_service.get_available_search_modes()
        return jsonify({
            'success': True,
            'search_modes': modes
        })
    except Exception as e:
        logger.error(f"获取搜索模式失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/collect/task/<task_id>/status')
def get_task_status(task_id):
    """获取任务状态"""
    try:
        result = paper_gather_service.get_task_result(task_id)
        if not result:
            return jsonify({
                'success': False,
                'error': '任务不存在'
            }), 404
        
        return jsonify({
            'success': True,
            'task_result': result
        })
    except Exception as e:
        logger.error(f"获取任务状态失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/collect/task/<task_id>/stop', methods=['POST'])
def stop_task(task_id):
    """停止任务"""
    try:
        success = paper_gather_service.stop_task(task_id)
        return jsonify({
            'success': success,
            'message': '任务停止成功' if success else '任务停止失败'
        })
    except Exception as e:
        logger.error(f"停止任务失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# === 论文浏览相关API (来自ExplorePaperData) ===

@api_bp.route('/explore/search')
def api_search():
    """搜索论文"""
    try:
        query = request.args.get('q', '').strip()
        task_name = request.args.get('task_name', '').strip()
        task_id = request.args.get('task_id', '').strip()
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 10)), 50)
        
        papers, total = paper_explore_service.search_papers(
            query=query,
            task_name=task_name,
            task_id=task_id,
            page=page, 
            per_page=per_page
        )
        
        return jsonify({
            'success': True,
            'data': papers,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        })
    
    except Exception as e:
        logger.error(f"API搜索失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/explore/stats')
def api_stats():
    """获取统计数据"""
    try:
        stats = paper_explore_service.get_overview_stats()
        return jsonify({'success': True, 'data': stats})
    
    except Exception as e:
        logger.error(f"API统计数据获取失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/explore/tasks')
def api_tasks():
    """获取可用任务列表"""
    try:
        tasks_data = paper_explore_service.get_available_tasks()
        # 将复杂的数据结构转换为简单的任务数组，供JavaScript迭代使用
        all_tasks = []
        
        # 添加基于任务名称的任务
        for task in tasks_data.get('task_names', []):
            all_tasks.append({
                'task_name': task['task_name'],
                'task_id': '',  # task_names中没有task_id
                'paper_count': task['paper_count']
            })
        
        # 添加基于任务ID的任务（避免重复）
        task_name_set = {task['task_name'] for task in all_tasks}
        for task in tasks_data.get('task_ids', []):
            if task['task_name'] not in task_name_set:
                all_tasks.append({
                    'task_name': task['task_name'],
                    'task_id': task['task_id'],
                    'paper_count': task['paper_count'],
                    'first_created': task.get('first_created'),
                    'last_created': task.get('last_created')
                })
        
        return jsonify({'success': True, 'data': {'tasks': all_tasks}})
    
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/explore/update_task_name', methods=['POST'])
def api_update_task_name():
    """更新任务名称"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '无效的请求数据'}), 400
        
        arxiv_id = data.get('arxiv_id')
        new_task_name = (data.get('new_task_name') or '').strip()
        
        if not arxiv_id:
            return jsonify({'success': False, 'error': '缺少论文ID'}), 400
            
        success = paper_explore_service.update_task_name(arxiv_id, new_task_name)
        
        if success:
            return jsonify({'success': True, 'message': '任务名称更新成功'})
        else:
            return jsonify({'success': False, 'error': '更新失败，论文不存在'}), 404
    
    except Exception as e:
        logger.error(f"更新任务名称失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/explore/delete_paper/<arxiv_id>', methods=['DELETE'])
def api_delete_paper(arxiv_id):
    """删除单个论文"""
    try:
        success = paper_explore_service.delete_paper(arxiv_id)
        
        if success:
            return jsonify({'success': True, 'message': '论文删除成功'})
        else:
            return jsonify({'success': False, 'error': '删除失败，论文不存在'}), 404
    
    except Exception as e:
        logger.error(f"删除论文失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# === 深度分析相关API ===

@api_bp.route('/analysis/paper/<arxiv_id>/analyze', methods=['POST'])
def api_start_analysis(arxiv_id):
    """启动深度论文分析"""
    try:
        logger.info(f"🎯 收到深度分析请求 - ArXiv ID: {arxiv_id}")
        
        # 获取配置参数
        data = request.get_json() if request.is_json else {}
        config = data.get('config', {})
        
        # 启动分析
        result = analysis_service.start_analysis(arxiv_id, config)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"启动深度分析失败 {arxiv_id}: {e}")
        return jsonify({
            'success': False,
            'error': f"启动分析失败: {str(e)}"
        }), 500


@api_bp.route('/analysis/paper/<arxiv_id>/status')
def api_analysis_status(arxiv_id):
    """查询分析状态"""
    try:
        result = analysis_service.get_analysis_status(arxiv_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 404
            
    except Exception as e:
        logger.error(f"获取分析状态失败 {arxiv_id}: {e}")
        return jsonify({
            'success': False,
            'error': f"获取状态失败: {str(e)}"
        }), 500


@api_bp.route('/analysis/paper/<arxiv_id>/result')
def api_analysis_result(arxiv_id):
    """获取分析结果"""
    try:
        result = analysis_service.get_analysis_result(arxiv_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 404
            
    except Exception as e:
        logger.error(f"获取分析结果失败 {arxiv_id}: {e}")
        return jsonify({
            'success': False,
            'error': f"获取结果失败: {str(e)}"
        }), 500


@api_bp.route('/analysis/config', methods=['GET'])
def get_analysis_config():
    """获取深度分析配置和可用模型"""
    try:
        # 导入LLMFactory
        from HomeSystem.graph.llm_factory import LLMFactory
        factory = LLMFactory()
        
        # 从Redis获取当前配置
        config_key = "analysis_config:global"
        current_config = {
            "analysis_model": "deepseek.DeepSeek_V3",
            "vision_model": "ollama.Qwen2_5_VL_7B",
            "timeout": 600
        }
        
        if redis_client:
            try:
                saved_config = redis_client.get(config_key)
                if saved_config:
                    current_config.update(json.loads(saved_config))
            except Exception as e:
                logger.warning(f"读取Redis配置失败: {e}")
        
        # 获取可用模型列表
        available_models = factory.get_available_llm_models()
        vision_models = factory.get_available_vision_models()
        
        return jsonify({
            'success': True,
            'data': {
                'current_config': current_config,
                'available_models': {
                    'analysis_models': available_models,
                    'vision_models': vision_models
                }
            }
        })
        
    except Exception as e:
        logger.error(f"获取分析配置失败: {e}")
        return jsonify({
            'success': False,
            'error': f"获取配置失败: {str(e)}"
        }), 500


@api_bp.route('/analysis/config', methods=['POST'])
def save_analysis_config():
    """保存深度分析配置"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '请求数据不能为空'
            }), 400
        
        # 验证必要字段
        analysis_model = data.get('analysis_model')
        vision_model = data.get('vision_model')
        timeout = data.get('timeout', 600)
        
        if not analysis_model or not vision_model:
            return jsonify({
                'success': False,
                'error': '分析模型和视觉模型不能为空'
            }), 400
        
        # 构建配置
        config = {
            'analysis_model': analysis_model,
            'vision_model': vision_model,
            'timeout': timeout
        }
        
        # 保存到Redis
        config_key = "analysis_config:global"
        if redis_client:
            try:
                redis_client.set(config_key, json.dumps(config))
                logger.info(f"配置已保存到Redis: {config}")
            except Exception as e:
                logger.error(f"保存配置到Redis失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'保存配置失败: {str(e)}'
                }), 500
        
        return jsonify({
            'success': True,
            'message': '配置保存成功',
            'config': config
        })
        
    except Exception as e:
        logger.error(f"保存分析配置失败: {e}")
        return jsonify({
            'success': False,
            'error': f"保存配置失败: {str(e)}"
        }), 500


@api_bp.route('/settings/save', methods=['POST'])
def save_settings():
    """保存系统设置（模型设置和深度分析设置）"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '请求数据不能为空'
            }), 400
        
        # 验证必要字段
        llm_model_name = data.get('llm_model_name')
        if not llm_model_name:
            return jsonify({
                'success': False,
                'error': 'LLM模型名称不能为空'
            }), 400
        
        # 构建配置
        config = {
            # LLM配置
            'llm_model_name': llm_model_name,
            'relevance_threshold': data.get('relevance_threshold', 0.7),
            'abstract_analysis_model': data.get('abstract_analysis_model'),
            'full_paper_analysis_model': data.get('full_paper_analysis_model'),
            'deep_analysis_model': data.get('deep_analysis_model'),
            'vision_model': data.get('vision_model'),
            
            # 深度分析配置
            'enable_deep_analysis': data.get('enable_deep_analysis', True),
            'deep_analysis_threshold': data.get('deep_analysis_threshold', 0.8),
            'ocr_char_limit_for_analysis': data.get('ocr_char_limit_for_analysis', 10000),
            'analysis_timeout': data.get('analysis_timeout', 600)
        }
        
        # 保存到Redis
        config_key = "system_settings:global"
        if redis_client:
            try:
                redis_client.set(config_key, json.dumps(config))
                logger.info(f"系统设置已保存到Redis: {config}")
            except Exception as e:
                logger.error(f"保存系统设置到Redis失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'保存设置失败: {str(e)}'
                }), 500
        
        return jsonify({
            'success': True,
            'message': '设置保存成功',
            'config': config
        })
        
    except Exception as e:
        logger.error(f"保存系统设置失败: {e}")
        return jsonify({
            'success': False,
            'error': f"保存设置失败: {str(e)}"
        }), 500


@api_bp.route('/settings/load', methods=['GET'])
def load_settings():
    """加载系统设置"""
    try:
        config_key = "system_settings:global"
        config = {}
        
        if redis_client:
            try:
                config_data = redis_client.get(config_key)
                if config_data:
                    config = json.loads(config_data)
                    logger.info(f"从Redis加载系统设置: {config}")
            except Exception as e:
                logger.error(f"从Redis加载系统设置失败: {e}")
        
        return jsonify({
            'success': True,
            'config': config
        })
        
    except Exception as e:
        logger.error(f"加载系统设置失败: {e}")
        return jsonify({
            'success': False,
            'error': f"加载设置失败: {str(e)}"
        }), 500


# === 系统状态相关API ===

@api_bp.route('/running_tasks')
def get_running_tasks():
    """获取运行中任务状态 - 用于首页实时更新"""
    try:
        # 获取运行中任务数量和详情
        running_count = paper_gather_service.get_running_tasks_count()
        running_details = paper_gather_service.get_running_tasks_detail()
        
        return jsonify({
            'success': True,
            'data': {
                'count': running_count,
                'details': running_details
            }
        })
    except Exception as e:
        logger.error(f"获取运行中任务失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/system_stats')
def get_system_stats():
    """获取系统核心统计数据 - 用于首页展示卡片"""
    try:
        # 获取论文收集统计
        collect_stats = paper_data_service.get_paper_statistics()
        
        # 获取运行中任务数量
        running_tasks_count = paper_gather_service.get_running_tasks_count()
        
        # 获取定时任务数量
        scheduled_tasks = paper_gather_service.get_scheduled_tasks()
        scheduled_count = len(scheduled_tasks) if scheduled_tasks else 0
        
        # 构建核心统计数据
        core_stats = {
            'total_papers': collect_stats.get('total_papers', 0),
            'analyzed_papers': collect_stats.get('analyzed_papers', 0),
            'running_tasks': running_tasks_count,
            'scheduled_tasks': scheduled_count
        }
        
        return jsonify({
            'success': True,
            'data': core_stats
        })
    except Exception as e:
        logger.error(f"获取系统统计数据失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========== 迁移和任务管理相关API ==========

@api_bp.route('/tasks/available_for_migration')
def api_get_available_tasks_for_migration():
    """获取可用于迁移的任务列表"""
    try:
        tasks = paper_explore_service.get_available_tasks()
        return jsonify({'success': True, 'data': {'tasks': tasks}})
    
    except Exception as e:
        logger.error(f"获取迁移任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/get_tasks')
def api_get_tasks():
    """获取所有任务列表（用于批量操作）"""
    try:
        tasks_data = paper_explore_service.get_available_tasks()
        # 将复杂的数据结构转换为简单的任务数组，供批量操作使用
        all_tasks = []
        
        # 添加基于任务名称的任务
        for task in tasks_data.get('task_names', []):
            all_tasks.append({
                'task_name': task['task_name'],
                'task_id': '',  # task_names中没有task_id
                'paper_count': task['paper_count'],
                'created_at': None  # task_names中没有时间信息
            })
        
        # 添加基于任务ID的任务（避免重复）
        task_name_set = {task['task_name'] for task in all_tasks}
        for task in tasks_data.get('task_ids', []):
            if task['task_name'] not in task_name_set:
                all_tasks.append({
                    'task_name': task['task_name'],
                    'task_id': task['task_id'],
                    'paper_count': task['paper_count'],
                    'created_at': task.get('last_created')  # 使用last_created作为展示时间
                })
        
        return jsonify({'success': True, 'tasks': all_tasks})
    
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/migrate_paper_to_task', methods=['POST'])
def api_migrate_paper_to_task():
    """单个论文迁移到新任务"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '无效的请求数据'}), 400
        
        arxiv_id = data.get('arxiv_id')
        target_task_name = data.get('target_task_name', '').strip()
        target_task_id = data.get('target_task_id', '').strip()
        
        if not arxiv_id or not target_task_name:
            return jsonify({'success': False, 'error': '缺少必要参数'}), 400
        
        success = paper_explore_service.migrate_paper_to_task(
            arxiv_id, target_task_name, target_task_id or None
        )
        
        if success:
            return jsonify({'success': True, 'message': '论文迁移成功'})
        else:
            return jsonify({'success': False, 'error': '迁移失败，论文不存在'}), 404
    
    except Exception as e:
        logger.error(f"论文迁移失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/batch_migrate_to_task', methods=['POST'])
def api_batch_migrate_to_task():
    """批量论文迁移到新任务"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '无效的请求数据'}), 400
        
        arxiv_ids = data.get('arxiv_ids', [])
        target_task_name = data.get('target_task_name', '').strip()
        target_task_id = data.get('target_task_id', '').strip()
        
        if not arxiv_ids or not target_task_name:
            return jsonify({'success': False, 'error': '缺少必要参数'}), 400
        
        affected_rows = paper_explore_service.batch_migrate_papers_to_task(
            arxiv_ids, target_task_name, target_task_id or None
        )
        
        return jsonify({
            'success': True, 
            'affected_rows': affected_rows,
            'message': f'成功迁移 {affected_rows} 篇论文'
        })
    
    except Exception as e:
        logger.error(f"批量迁移失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/assign_task_to_paper', methods=['POST'])
def api_assign_task_to_paper():
    """为论文分配任务"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '无效的请求数据'}), 400
        
        arxiv_id = data.get('arxiv_id')
        task_name = data.get('task_name', '').strip()
        task_id = data.get('task_id', '').strip()
        
        if not arxiv_id or not task_name:
            return jsonify({'success': False, 'error': '缺少必要参数'}), 400
        
        success = paper_explore_service.assign_task_to_paper(
            arxiv_id, task_name, task_id or None
        )
        
        if success:
            return jsonify({'success': True, 'message': '任务分配成功'})
        else:
            return jsonify({'success': False, 'error': '分配失败，论文不存在'}), 404
    
    except Exception as e:
        logger.error(f"任务分配失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/batch_assign_task', methods=['POST'])
def api_batch_assign_task():
    """批量分配任务"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '无效的请求数据'}), 400
        
        arxiv_ids = data.get('arxiv_ids', [])
        task_name = data.get('task_name', '').strip()
        task_id = data.get('task_id', '').strip()
        
        if not arxiv_ids or not task_name:
            return jsonify({'success': False, 'error': '缺少必要参数'}), 400
        
        affected_rows = paper_explore_service.batch_assign_task_to_papers(
            arxiv_ids, task_name, task_id or None
        )
        
        return jsonify({
            'success': True, 
            'affected_rows': affected_rows,
            'message': f'成功为 {affected_rows} 篇论文分配任务'
        })
    
    except Exception as e:
        logger.error(f"批量分配任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# === 下载分析相关API ===

@api_bp.route('/paper/<arxiv_id>/download_analysis')
def api_download_analysis(arxiv_id):
    """API接口 - 下载分析结果（Markdown + 图片打包为ZIP）"""
    try:
        # 获取分析结果
        result = analysis_service.get_analysis_result(arxiv_id)
        
        if not result['success']:
            return jsonify({
                'success': False,
                'error': '分析结果不存在'
            }), 404
        
        # 创建临时ZIP文件
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        
        try:
            with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                # 添加Markdown文件
                markdown_content = result['content']
                
                # 处理图片路径，转换为相对路径
                processed_markdown = _process_markdown_for_download(markdown_content, arxiv_id)
                
                zip_file.writestr(f"{arxiv_id}_analysis.md", processed_markdown)
                
                # 添加图片文件
                images_dir = os.path.join(PROJECT_ROOT, "data/paper_analyze", arxiv_id, "imgs")
                if os.path.exists(images_dir):
                    for filename in os.listdir(images_dir):
                        if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            image_path = os.path.join(images_dir, filename)
                            if os.path.isfile(image_path):
                                zip_file.write(image_path, f"imgs/{filename}")
            
            # 返回ZIP文件
            return send_file(
                temp_zip.name,
                as_attachment=True,
                download_name=f"{arxiv_id}_deep_analysis.zip",
                mimetype='application/zip'
            )
            
        finally:
            # 清理临时文件（在发送后会被自动删除）
            pass
            
    except Exception as e:
        logger.error(f"下载分析结果失败 {arxiv_id}: {e}")
        return jsonify({
            'success': False,
            'error': f"下载失败: {str(e)}"
        }), 500


def _process_markdown_for_download(content: str, arxiv_id: str) -> str:
    """
    处理Markdown内容，将网页URL路径转换为本地相对路径
    
    Args:
        content: 原始Markdown内容
        arxiv_id: ArXiv论文ID
        
    Returns:
        str: 处理后的Markdown内容
    """
    try:
        # 将网页URL路径转换为相对路径
        pattern = rf'/paper/{re.escape(arxiv_id)}/analysis_images/([^)]+)'
        replacement = r'imgs/\1'
        
        processed_content = re.sub(pattern, replacement, content)
        
        return processed_content
        
    except Exception as e:
        logger.error(f"处理Markdown下载内容失败: {e}")
        return content