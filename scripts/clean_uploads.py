
import os
import shutil
import time
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/cleanup.log'),
        logging.StreamHandler()
    ]
)

# 必须与 app.py 中的配置保持一致
UPLOAD_FOLDER = '/tmp/flask_uploads'
MAX_AGE_SECONDS = 3600  # 1小时过期 (3600秒)

def clean_expired_uploads():
    """清理过期的上传文件夹"""
    logging.info(f"Starting cleanup scan in {UPLOAD_FOLDER}")
    
    if not os.path.exists(UPLOAD_FOLDER):
        logging.info("Upload folder does not exist. Skipping.")
        return

    count = 0
    now = time.time()
    
    try:
        for user_dir in os.listdir(UPLOAD_FOLDER):
            dir_path = os.path.join(UPLOAD_FOLDER, user_dir)
            
            # 确保是目录
            if not os.path.isdir(dir_path):
                continue
                
            try:
                # 获取最后修改时间
                mtime = os.path.getmtime(dir_path)
                
                # 检查是否过期
                if now - mtime > MAX_AGE_SECONDS:
                    shutil.rmtree(dir_path)
                    count += 1
                    logging.info(f"Deleted expired session: {user_dir}")
                    
            except OSError as e:
                logging.error(f"Error accessing/deleting {dir_path}: {e}")
                
    except Exception as e:
        logging.error(f"Cleanup failed: {e}")
        
    logging.info(f"Cleanup finished. Removed {count} expired directories.")

if __name__ == '__main__':
    clean_expired_uploads()
