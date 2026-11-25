import os
import sys
from pathlib import Path

current_file_path = Path(__file__).resolve()
current_dir = current_file_path.parent
JS_SCRIPT_PATH = current_dir / 'javascript'

# node 环境变量注入（原项目在 import 时自动执行；拆出来避免 import 副作用，
# 由 backend/app.py 启动时显式调用）
execute_dir = os.path.split(os.path.realpath(sys.argv[0]))[0]
node_execute_dir = Path(execute_dir) / 'node'
current_env_path = os.environ.get('PATH', '')
os.environ['PATH'] = str(node_execute_dir) + os.pathsep + current_env_path

def ensure_runtime():
    """启动时调用：校验/安装 node（X-Bogus 签名需要）。原 check_node 封装。"""
    from .initializer import check_node
    check_node()
