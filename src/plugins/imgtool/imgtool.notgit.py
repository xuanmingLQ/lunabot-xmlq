import numpy as np
import cv2
from PIL import Image
from typing import List, Union

# --- 高性能核心逻辑 ---

def _cutout_logic_cv2(img_array: np.ndarray, tolerance: int) -> np.ndarray:
    """
    使用 OpenCV 的 C++ 级泛洪填充实现极速抠图
    """
    n, h, w, _ = img_array.shape
    # OpenCV 的 loDiff 和 upDiff 是针对每个通道的容差
    # 为了匹配 C++ 的平方距离，这里取 tolerance 作为各通道的阈值
    diff = (tolerance, tolerance, tolerance, 255) 
    
    # 1. 确定背景参考色：取第一帧四个边缘最频繁的颜色
    f0 = img_array[0]
    edges = np.concatenate([f0[0, :], f0[-1, :], f0[:, 0], f0[:, -1]])
    # 找到边缘出现次数最多的颜色
    unique_colors, counts = np.unique(edges, axis=0, return_counts=True)
    max_color = unique_colors[np.argmax(counts)]
    
    # 目标颜色：全透明黑色
    dst_color = (0, 0, 0, 0)

    # 2. 逐帧处理
    for t in range(n):
        frame = img_array[t]
        
        # 边缘触发泛洪
        # 左右边缘
        for y in range(h):
            for x in [0, w - 1]:
                if frame[y, x, 3] != 0: # 只有非透明点才触发
                    # 计算当前像素与背景色的差值，手动做个预检以减少无用调用
                    if np.max(np.abs(frame[y, x, :3].astype(np.int32) - max_color[:3].astype(np.int32))) <= tolerance:
                        cv2.floodFill(frame, None, (x, y), dst_color, diff, diff)
        # 上下边缘
        for x in range(w):
            for y in [0, h - 1]:
                if frame[y, x, 3] != 0:
                    if np.max(np.abs(frame[y, x, :3].astype(np.int32) - max_color[:3].astype(np.int32))) <= tolerance:
                        cv2.floodFill(frame, None, (x, y), dst_color, diff, diff)
                        
    return img_array

def _shrink_logic_numpy(img_array: np.ndarray, alpha_threshold: int, edge: int) -> np.ndarray:
    """
    利用 NumPy 矢量化操作实现极速裁剪
    """
    # 找到所有 Alpha > threshold 的索引
    # axis=(1,2) 忽略时间轴，直接找空间上的最大范围
    alpha_mask = img_array[..., 3] > alpha_threshold
    coords = np.argwhere(alpha_mask)

    if coords.size == 0:
        return np.zeros((1, 1, 1, 4), dtype=np.uint8)

    # 计算 n, h, w 三个维度的最小最大值
    t_min, y_min, x_min = coords.min(axis=0)
    t_max, y_max, x_max = coords.max(axis=0)

    # 裁剪核心内容
    content = img_array[t_min:t_max+1, y_min:y_max+1, x_min:x_max+1]
    
    # 使用 np.pad 一次性完成边缘扩充（对应 C++ 的 new_img + memset）
    return np.pad(content, ((0, 0), (edge, edge), (edge, edge), (0, 0)), mode='constant')

# --- 业务调用接口 ---

def execute_imgtool_py(
    image: Union[Image.Image, List[Image.Image]], 
    command: str, 
    *args
) -> Union[Image.Image, List[Image.Image]]:
    """
    高性能图像处理接口
    """
    is_single_frame = isinstance(image, Image.Image)
    frames = [image] if is_single_frame else image
    
    # 1. 确保所有图片转换为 RGBA
    img_array = np.stack([np.array(img.convert('RGBA')) for img in frames])
    
    # 2. 根据命令调用
    if command == "cutout":
        tolerance = int(args[0])
        # OpenCV 的核心操作
        processed = _cutout_logic_cv2(img_array, tolerance)
    elif command == "shrink":
        threshold, edge_size = int(args[0]), int(args[1])
        processed = _shrink_logic_numpy(img_array, threshold, edge_size)
    else:
        raise ValueError(f"未知命令: {command}")
    
    # 3. 批量转回 PIL
    result_images = [Image.fromarray(f) for f in processed]
    
    return result_images[0] if is_single_frame else result_images