import os
import re
import aiohttp
import asyncio
from aiohttp import ClientSession
from bs4 import BeautifulSoup

async def cython_download_file(url, file_name, session, save_path, progress_signal, log_signal, proxy=None, max_retries=60, request_timeout=60):
    retries = 0
    while retries < max_retries:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=request_timeout), proxy=proxy
            ) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                block_size = 4096

                if not os.path.exists(save_path):
                    os.makedirs(save_path)

                file_path = os.path.join(save_path, file_name)
                temp_path = file_path + ".part"

                with open(temp_path, "wb") as f:
                    downloaded_size = 0
                    async for data in response.content.iter_chunked(block_size):
                        f.write(data)
                        downloaded_size += len(data)
                        progress = ((downloaded_size / total_size) * 100 if total_size else 0)
                        progress_signal.emit(progress)
                        log_signal.emit(f"下载进度: {progress:.2f}%")

                if os.path.exists(file_path):
                    log_signal.emit(f"文件已存在: {file_path}")
                    os.remove(temp_path)
                else:
                    os.rename(temp_path, file_path)
                return
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log_signal.emit(f"下载失败: {e}")
            retries += 1
            await asyncio.sleep(10)

            if os.path.exists(temp_path):
                os.remove(temp_path)
            if os.path.exists(file_path) and not os.path.exists(temp_path):
                os.remove(file_path)

    log_signal.emit("达到最大重试次数，放弃下载。")