#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gesture Rhythm Master - Piano Mode
使用88键钢琴采样 - 正确映射所有音符（支持升降号）
"""

import cv2
import mediapipe as mp
import pygame
import pygame.gfxdraw
import numpy as np
import time
import os
import threading
import random
import math
import subprocess
import warnings
import urllib.request
from io import BytesIO
from functools import lru_cache
from collections import defaultdict
import glob
import re

# 抑制所有警告
warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['MEDIAPIPE_DISABLE_GPU'] = '1'

# ============================================
# 🎵 Audio Setup - 使用真实钢琴采样（单声道）
# ============================================
pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=1024)
pygame.init()

# 设置大量音频通道
pygame.mixer.set_num_channels(64)

# 获取显示器信息
info = pygame.display.Info()
MONITOR_WIDTH = info.current_w
MONITOR_HEIGHT = info.current_h

# Screen settings - 全屏模式
SCREEN_WIDTH = MONITOR_WIDTH
SCREEN_HEIGHT = MONITOR_HEIGHT

# 侧边栏宽度
SIDEBAR_WIDTH = 300
GAME_WIDTH = SCREEN_WIDTH - SIDEBAR_WIDTH
GAME_HEIGHT = SCREEN_HEIGHT

# 摄像头预览窗口尺寸
CAMERA_PREVIEW_WIDTH = 280
CAMERA_PREVIEW_HEIGHT = 210
CAMERA_PREVIEW_X = GAME_WIDTH + (SIDEBAR_WIDTH - CAMERA_PREVIEW_WIDTH) // 2
CAMERA_PREVIEW_Y = 30

# 设置全屏
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
pygame.display.set_caption("Gesture Rhythm Master - Piano Mode")

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (128, 128, 128)
DARK_GRAY = (50, 50, 50)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 100, 255)
YELLOW = (255, 255, 0)
PURPLE = (255, 0, 255)
CYAN = (0, 255, 255)
ORANGE = (255, 128, 0)
GOLD = (255, 215, 0)
SILVER = (192, 192, 192)
DARK_BG = (30, 30, 40)
DARK_OVERLAY = (0, 0, 0, 180)

# ============================================
# 🎹 88键钢琴采样映射（tone 1-88 对应 A0-C8）
# ============================================

# 采样文件目录
SAMPLES_DIR = os.path.expanduser("~/Piano")

# 88键钢琴所有音符（从A0到C8）
# MIDI编号: A0=21, A#0=22, B0=23, C1=24, ... C8=108
NOTE_NAMES_88 = [
    'A0', 'A#0', 'B0',
    'C1', 'C#1', 'D1', 'D#1', 'E1', 'F1', 'F#1', 'G1', 'G#1', 'A1', 'A#1', 'B1',
    'C2', 'C#2', 'D2', 'D#2', 'E2', 'F2', 'F#2', 'G2', 'G#2', 'A2', 'A#2', 'B2',
    'C3', 'C#3', 'D3', 'D#3', 'E3', 'F3', 'F#3', 'G3', 'G#3', 'A3', 'A#3', 'B3',
    'C4', 'C#4', 'D4', 'D#4', 'E4', 'F4', 'F#4', 'G4', 'G#4', 'A4', 'A#4', 'B4',
    'C5', 'C#5', 'D5', 'D#5', 'E5', 'F5', 'F#5', 'G5', 'G#5', 'A5', 'A#5', 'B5',
    'C6', 'C#6', 'D6', 'D#6', 'E6', 'F6', 'F#6', 'G6', 'G#6', 'A6', 'A#6', 'B6',
    'C7', 'C#7', 'D7', 'D#7', 'E7', 'F7', 'F#7', 'G7', 'G#7', 'A7', 'A#7', 'B7',
    'C8'
]

# 降号到升号的映射
FLAT_TO_SHARP = {
    'Cb': 'B', 'Db': 'C#', 'Eb': 'D#', 'Fb': 'E',
    'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#', 'E#': 'F', 'B#': 'C'
}

# 创建包含别名映射的查找字典
NOTE_INDEX_LOOKUP = {}
for i, note in enumerate(NOTE_NAMES_88):
    NOTE_INDEX_LOOKUP[note] = i
    # 添加降号别名
    if '#' in note and len(note) >= 2:
        note_name = note[:-1]  # 去掉八度数字
        octave = note[-1]
        for flat, sharp in FLAT_TO_SHARP.items():
            if sharp == note_name:
                flat_note = flat + octave
                NOTE_INDEX_LOOKUP[flat_note] = i
                break

# 音符名称到MIDI编号的映射
NOTE_TO_MIDI = {note: 21 + i for i, note in enumerate(NOTE_NAMES_88)}
# 也添加降号别名
for flat, sharp in FLAT_TO_SHARP.items():
    for i, note in enumerate(NOTE_NAMES_88):
        if note.startswith(sharp):
            octave = note[-1]
            flat_note = flat + octave
            NOTE_TO_MIDI[flat_note] = 21 + i
            break

# MIDI编号到音符名称的反向映射
MIDI_TO_NOTE = {v: k for k, v in NOTE_TO_MIDI.items()}

# 缓存
SAMPLE_SOUND_CACHE = {}
SAMPLE_CACHE_MAX = 500

# ============================================
# 🎵 音频通道管理
# ============================================

class AudioManager:
    """管理音频通道，确保音符完整播放"""
    
    def __init__(self):
        self.playing_notes = {}
        self.next_channel_id = 0
        self.lock = threading.Lock()
        self.max_channels = 64
        
    def play_sound(self, sound, note_name="", volume=1.0):
        """播放声音，确保完整播放"""
        with self.lock:
            self._cleanup_stopped_channels()
            
            sound.set_volume(min(1.0, volume))
            
            channel = None
            for i in range(self.max_channels):
                ch = pygame.mixer.Channel(i)
                if not ch.get_busy():
                    channel = ch
                    break
            
            if channel is None:
                oldest_id = None
                oldest_time = float('inf')
                for ch_id, (_, start_time, _, _) in self.playing_notes.items():
                    if start_time < oldest_time:
                        oldest_time = start_time
                        oldest_id = ch_id
                
                if oldest_id is not None:
                    old_ch = self.playing_notes[oldest_id][3]
                    old_ch.stop()
                    del self.playing_notes[oldest_id]
                    channel = old_ch
                else:
                    channel = pygame.mixer.Channel(0)
                    channel.stop()
            
            channel.play(sound)
            
            ch_id = self.next_channel_id
            self.next_channel_id += 1
            self.playing_notes[ch_id] = (note_name, time.time(), sound, channel)
            
            self._cleanup_stopped_channels()
            
            return channel
    
    def _cleanup_stopped_channels(self):
        """清理已停止的通道"""
        to_remove = []
        for ch_id, (_, _, _, channel) in self.playing_notes.items():
            if not channel.get_busy():
                to_remove.append(ch_id)
        for ch_id in to_remove:
            del self.playing_notes[ch_id]
    
    def get_playing_count(self):
        self._cleanup_stopped_channels()
        return len(self.playing_notes)
    
    def stop_all(self):
        with self.lock:
            for _, (_, _, _, channel) in self.playing_notes.items():
                channel.stop()
            self.playing_notes.clear()

# 全局音频管理器
audio_manager = AudioManager()

# ============================================
# 🎹 采样加载函数
# ============================================

def get_sample_file_for_note(note_name):
    """
    根据音符名称查找对应的采样文件
    支持降号 (b) 和升号 (#) 两种格式
    """
    # 尝试直接查找（包括别名）
    if note_name in NOTE_INDEX_LOOKUP:
        index = NOTE_INDEX_LOOKUP[note_name]
    else:
        # 尝试解析并转换
        note, octave = parse_note_name_simple(note_name)
        
        # 检查是否是降号音符
        if note in FLAT_TO_SHARP:
            sharp_note = FLAT_TO_SHARP[note]
            test_name = f"{sharp_note}{octave}"
            if test_name in NOTE_INDEX_LOOKUP:
                index = NOTE_INDEX_LOOKUP[test_name]
            else:
                return None
        else:
            test_name = f"{note}{octave}"
            if test_name in NOTE_INDEX_LOOKUP:
                index = NOTE_INDEX_LOOKUP[test_name]
            else:
                return None
    
    # 文件名格式: tone (1).wav 到 tone (88).wav
    filename = f"tone ({index + 1}).wav"
    filepath = os.path.join(SAMPLES_DIR, filename)
    
    if os.path.exists(filepath):
        return filepath
    
    return None

def parse_note_name_simple(note_name):
    """简单解析音符名称，返回 (note, octave)"""
    # 处理简谱格式
    if note_name in ['1', '2', '3', '4', '5', '6', '7']:
        scale_map = {'1': 'C', '2': 'D', '3': 'E', '4': 'F', '5': 'G', '6': 'A', '7': 'B'}
        return scale_map[note_name], 4
    
    # 处理带 ' 的简谱 (如 1', 2' 等)
    if len(note_name) >= 1 and note_name[0].isdigit():
        scale_map = {'1': 'C', '2': 'D', '3': 'E', '4': 'F', '5': 'G', '6': 'A', '7': 'B'}
        note = scale_map.get(note_name[0], 'C')
        octave = 4
        octave_offset = note_name.count('\'')
        has_low = '̣' in note_name
        if has_low:
            octave -= 1
        octave += octave_offset
        return note, octave
    
    # 处理带升降号的音符 (如 Eb4, Bb5, C#5)
    if len(note_name) >= 2:
        if note_name[1] in ['#', 'b']:
            note = note_name[:2]
            octave = int(note_name[2:]) if len(note_name) > 2 and note_name[2:].isdigit() else 4
            return note, octave
    
    # 处理普通音符 (如 C4, D5)
    if len(note_name) >= 1 and note_name[0].isalpha():
        note = note_name[0]
        octave_str = ''
        for ch in note_name[1:]:
            if ch.isdigit():
                octave_str += ch
            else:
                break
        octave = int(octave_str) if octave_str else 4
        return note, octave
    
    return 'C', 4

def load_piano_sample(note_name, velocity=8):
    """加载钢琴采样音频 - 只加载不播放"""
    cache_key = f"{note_name}_{velocity}"
    
    if cache_key in SAMPLE_SOUND_CACHE:
        return SAMPLE_SOUND_CACHE[cache_key]
    
    filepath = get_sample_file_for_note(note_name)
    
    if filepath is None:
        # 如果找不到采样，打印警告并尝试找最近的音符
        print(f"  ⚠️ 未找到采样: {note_name}")
        # 尝试找相同音符名的其他八度
        note, octave = parse_note_name_simple(note_name)
        for test_octave in [4, 3, 5, 2, 6, 1, 7]:
            test_name = f"{note}{test_octave}"
            filepath = get_sample_file_for_note(test_name)
            if filepath:
                print(f"    🔄 使用替代: {test_name}")
                break
        if filepath is None:
            # 如果还是找不到，使用C4
            filepath = get_sample_file_for_note('C4')
            if filepath is None:
                # 极端情况，使用第一个采样
                sample_files = glob.glob(os.path.join(SAMPLES_DIR, "tone*.wav"))
                if sample_files:
                    filepath = sample_files[0]
                else:
                    return None
    
    try:
        sound = pygame.mixer.Sound(filepath)
        
        if len(SAMPLE_SOUND_CACHE) > SAMPLE_CACHE_MAX:
            keys = list(SAMPLE_SOUND_CACHE.keys())[:SAMPLE_CACHE_MAX // 2]
            for k in keys:
                del SAMPLE_SOUND_CACHE[k]
        
        SAMPLE_SOUND_CACHE[cache_key] = sound
        return sound
        
    except Exception as e:
        print(f"  ❌ 加载采样失败 {note_name}: {e}")
        return None

def get_note_sound(note_name, duration=0.15, velocity=0.8, play_immediately=True):
    """
    获取音符声音并播放
    """
    sample_velocity = max(1, min(16, int(velocity * 16)))
    
    # 根据时值调整音量
    volume_factor = 0.7 + 0.3 * min(1.0, duration / 0.3)
    
    # 对于高音（C5以上），增加音量补偿
    note, octave = parse_note_name_simple(note_name)
    if octave >= 5:
        volume_factor *= 1.15
    elif octave >= 6:
        volume_factor *= 1.3
    
    sound = load_piano_sample(note_name, sample_velocity)
    
    if sound is None:
        return None
    
    final_volume = min(1.0, 0.8 * volume_factor)
    sound.set_volume(final_volume)
    
    if play_immediately:
        audio_manager.play_sound(sound, note_name, final_volume)
    
    return sound

# ============================================
# 🔤 字体设置
# ============================================
font_scale = min(SCREEN_WIDTH, SCREEN_HEIGHT) / 1080

MONO_FONT_PATH = None
font_paths = [
    '/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    '/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf',
    '/System/Library/Fonts/Menlo.ttc',
    'C:/Windows/Fonts/consola.ttf',
    '/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf',
]

for path in font_paths:
    if os.path.exists(path):
        MONO_FONT_PATH = path
        break

print(f"字体路径: {MONO_FONT_PATH if MONO_FONT_PATH else '使用默认字体'}")

if MONO_FONT_PATH:
    FONT_MONO_LARGE = pygame.font.Font(MONO_FONT_PATH, int(72 * font_scale))
    FONT_MONO_MEDIUM = pygame.font.Font(MONO_FONT_PATH, int(44 * font_scale))
    FONT_MONO_SMALL = pygame.font.Font(MONO_FONT_PATH, int(32 * font_scale))
    FONT_MONO_TINY = pygame.font.Font(MONO_FONT_PATH, int(24 * font_scale))
    FONT_MONO_XS = pygame.font.Font(MONO_FONT_PATH, int(18 * font_scale))
    FONT_MONO_XLARGE = pygame.font.Font(MONO_FONT_PATH, int(120 * font_scale))
else:
    FONT_MONO_LARGE = pygame.font.Font(None, int(72 * font_scale))
    FONT_MONO_MEDIUM = pygame.font.Font(None, int(44 * font_scale))
    FONT_MONO_SMALL = pygame.font.Font(None, int(32 * font_scale))
    FONT_MONO_TINY = pygame.font.Font(None, int(24 * font_scale))
    FONT_MONO_XS = pygame.font.Font(None, int(18 * font_scale))
    FONT_MONO_XLARGE = pygame.font.Font(None, int(120 * font_scale))

FONT_LARGE = pygame.font.Font(None, int(90 * font_scale))
FONT_MEDIUM = pygame.font.Font(None, int(54 * font_scale))
FONT_SMALL = pygame.font.Font(None, int(38 * font_scale))
FONT_TINY = pygame.font.Font(None, int(28 * font_scale))
FONT_XS = pygame.font.Font(None, int(20 * font_scale))
FONT_XLARGE = pygame.font.Font(None, int(120 * font_scale))

# 预渲染文本缓存
PRERENDERED_TEXTS = {}
TEXT_CACHE_MAX_SIZE = 200

def get_prerendered_text(font, text, color):
    key = (id(font), text, color[0], color[1], color[2])
    if key not in PRERENDERED_TEXTS:
        if len(PRERENDERED_TEXTS) > TEXT_CACHE_MAX_SIZE:
            keys_to_remove = list(PRERENDERED_TEXTS.keys())[:TEXT_CACHE_MAX_SIZE // 2]
            for k in keys_to_remove:
                del PRERENDERED_TEXTS[k]
        PRERENDERED_TEXTS[key] = font.render(text, True, color)
    return PRERENDERED_TEXTS[key]

def prewarm_text_cache():
    """预热文本缓存"""
    common_texts = [
        ("PAUSED", YELLOW), ("DEMO MODE", CYAN), ("Game Info", WHITE),
        ("Score", WHITE), ("Statistics", WHITE), ("Start Game", WHITE),
        ("Auto Demo", WHITE), ("Quit", WHITE), ("Resume", WHITE),
        ("Quit to Menu", WHITE), ("Select Song", YELLOW), ("Select Difficulty", YELLOW),
        ("Back", WHITE), ("Play Again", WHITE), ("Back to Menu", WHITE),
        ("PERFECT!", GREEN), ("GREAT!", CYAN), ("GOOD", BLUE), ("MISS", RED),
        ("AUTO", CYAN), ("Song Complete!", YELLOW), ("Demo Complete!", CYAN),
        ("Loading...", WHITE), ("finalizing", CYAN)
    ]
    
    fonts = [FONT_MONO_LARGE, FONT_MONO_MEDIUM, FONT_MONO_SMALL, FONT_MONO_TINY, 
             FONT_MONO_XLARGE, FONT_XLARGE, FONT_LARGE, FONT_MEDIUM, FONT_SMALL, FONT_TINY]
    
    for text, color in common_texts:
        for font in fonts:
            get_prerendered_text(font, text, color)

prewarm_text_cache()

# ============================================
# 🎨 圆角矩形绘制函数（带缓存）
# ============================================

ROUNDED_RECT_CACHE = {}
RECT_CACHE_MAX_SIZE = 200

def draw_rounded_rect_aa(surface, color, rect, radius, border_width=0):
    if isinstance(rect, pygame.Rect):
        x, y, w, h = rect.x, rect.y, rect.width, rect.height
    else:
        x, y, w, h = rect
    
    x, y, w, h = int(x), int(y), int(w), int(h)
    radius = int(min(radius, w // 2, h // 2))
    border_width = int(border_width)
    
    if w < 2 or h < 2:
        return
    
    cache_key = (x, y, w, h, radius, border_width, color[0], color[1], color[2])
    
    if cache_key in ROUNDED_RECT_CACHE:
        temp = ROUNDED_RECT_CACHE[cache_key]
        surface.blit(temp, (x, y))
        return
    
    temp = pygame.Surface((w, h), pygame.SRCALPHA)
    temp.fill((0, 0, 0, 0))
    
    if border_width > 0:
        _draw_border_rounded(temp, color, 0, 0, w, h, radius, border_width)
    else:
        _draw_filled_rounded(temp, color, 0, 0, w, h, radius)
    
    if len(ROUNDED_RECT_CACHE) > RECT_CACHE_MAX_SIZE:
        keys_to_remove = list(ROUNDED_RECT_CACHE.keys())[:RECT_CACHE_MAX_SIZE // 2]
        for k in keys_to_remove:
            del ROUNDED_RECT_CACHE[k]
    ROUNDED_RECT_CACHE[cache_key] = temp
    
    surface.blit(temp, (x, y))

def _draw_filled_rounded(surface, color, x, y, w, h, r):
    x, y, w, h, r = int(x), int(y), int(w), int(h), int(r)
    
    if r <= 0:
        pygame.draw.rect(surface, color, (x, y, w, h))
        return
    
    pygame.draw.rect(surface, color, (x + r, y, w - 2*r, h))
    pygame.draw.rect(surface, color, (x, y + r, w, h - 2*r))
    pygame.draw.circle(surface, color, (x + r, y + r), r)
    pygame.draw.circle(surface, color, (x + w - r - 1, y + r), r)
    pygame.draw.circle(surface, color, (x + r, y + h - r - 1), r)
    pygame.draw.circle(surface, color, (x + w - r - 1, y + h - r - 1), r)

def _draw_border_rounded(surface, color, x, y, w, h, r, bw):
    x, y, w, h, r, bw = int(x), int(y), int(w), int(h), int(r), int(bw)
    
    if r <= 0:
        pygame.draw.rect(surface, color, (x, y, w, h), bw)
        return
    
    _draw_filled_rounded(surface, color, x, y, w, h, r)
    
    inner_x = x + bw
    inner_y = y + bw
    inner_w = w - 2*bw
    inner_h = h - 2*bw
    inner_r = max(0, r - bw)
    
    if inner_w > 0 and inner_h > 0:
        _draw_filled_rounded(surface, (0, 0, 0, 0), inner_x, inner_y, inner_w, inner_h, inner_r)

def draw_rounded_rect_alpha(surface, color_alpha, rect, radius, border_width=0, border_color_alpha=None):
    if isinstance(rect, pygame.Rect):
        x, y, w, h = rect.x, rect.y, rect.width, rect.height
    else:
        x, y, w, h = rect
    
    x, y, w, h = int(x), int(y), int(w), int(h)
    radius = int(radius)
    border_width = int(border_width)
    
    if w < 2 or h < 2:
        return
    
    if border_width > 0 and border_color_alpha:
        draw_rounded_rect_aa(surface, border_color_alpha, (x, y, w, h), radius, border_width)
        inner_rect = (x + border_width, y + border_width, w - 2*border_width, h - 2*border_width)
        if inner_rect[2] > 0 and inner_rect[3] > 0:
            draw_rounded_rect_aa(surface, color_alpha, inner_rect, max(0, radius - border_width))
    else:
        draw_rounded_rect_aa(surface, color_alpha, (x, y, w, h), radius)

# ============================================
# 📥 背景图片管理
# ============================================

BG_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bg_cache')

def ensure_cache_dir():
    if not os.path.exists(BG_CACHE_DIR):
        os.makedirs(BG_CACHE_DIR)

def download_image(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            image_data = response.read()
            image = pygame.image.load(BytesIO(image_data))
            return image, image_data
    except Exception as e:
        print(f"下载图片失败: {e}")
        return None, None

BG_GRADIENT_CACHE = {}

def create_fallback_bg(width, height, color1, color2):
    cache_key = (width, height, color1, color2)
    if cache_key in BG_GRADIENT_CACHE:
        return BG_GRADIENT_CACHE[cache_key].copy()
    
    bg = pygame.Surface((width, height))
    for y in range(height):
        ratio = y / height
        r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
        g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
        b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
        pygame.draw.line(bg, (r, g, b), (0, y), (width, y))
    
    BG_GRADIENT_CACHE[cache_key] = bg
    return bg.copy()

def load_bg_images():
    ensure_cache_dir()
    
    bg_urls = {
        'main': 'https://images.unsplash.com/photo-1519681393784-d120267933ba?w=1920&q=80',
        'song': 'https://images.unsplash.com/photo-1507838153414-b4b713384a76?w=1920&q=80',
        'pause': 'https://images.unsplash.com/photo-1519681393784-d120267933ba?w=1920&q=80',
        'result': 'https://images.unsplash.com/photo-1500462918059-b1a0cb512f1d?w=1920&q=80',
    }
    
    fallback_configs = {
        'main': ((20, 20, 50), (60, 30, 80)),
        'song': ((20, 50, 30), (30, 70, 50)),
        'pause': ((50, 30, 30), (70, 40, 40)),
        'result': ((40, 30, 20), (80, 50, 30)),
    }
    
    bg_images = {}
    need_download = []
    
    for key, url in bg_urls.items():
        local_path = os.path.join(BG_CACHE_DIR, f'{key}.jpg')
        
        if os.path.exists(local_path):
            try:
                img = pygame.image.load(local_path)
                bg_images[key] = pygame.transform.scale(img, (SCREEN_WIDTH, SCREEN_HEIGHT))
                continue
            except:
                try:
                    os.remove(local_path)
                except:
                    pass
        
        need_download.append(key)
    
    if need_download:
        for key in need_download:
            url = bg_urls[key]
            img, image_data = download_image(url)
            
            if img and image_data:
                local_path = os.path.join(BG_CACHE_DIR, f'{key}.jpg')
                try:
                    with open(local_path, 'wb') as f:
                        f.write(image_data)
                except:
                    pass
                
                bg_images[key] = pygame.transform.scale(img, (SCREEN_WIDTH, SCREEN_HEIGHT))
            else:
                color1, color2 = fallback_configs[key]
                bg_images[key] = create_fallback_bg(SCREEN_WIDTH, SCREEN_HEIGHT, color1, color2)
    
    return bg_images

print("🖼️ 加载背景图片...")
bg_images = load_bg_images()
print("✅ 背景图片加载完成")

# ============================================
# 📷 Camera Manager
# ============================================

class CameraManager:
    def __init__(self, fps=90):
        self.frame = None
        self.frame_lock = threading.Lock()
        self.running = True
        self.fps = 0
        self.process = None
        self.cap = None
        self.available = False
        self.initialized = False
        self.frame_count = 0
        self.fps_start = time.time()
        self.last_valid_frame = None
        
        self.pipe_path = '/tmp/camera_pipe'
        if os.path.exists(self.pipe_path):
            try:
                os.unlink(self.pipe_path)
            except:
                pass
        
        try:
            os.mkfifo(self.pipe_path)
        except:
            return
        
        cmd = [
            'rpicam-vid',
            '-t', '0',
            '--width', '320',
            '--height', '240',
            '--framerate', str(fps),
            '--codec', 'mjpeg',
            '--nopreview',
            '--output', self.pipe_path
        ]
        
        try:
            self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.init_thread = threading.Thread(target=self._init_camera, daemon=True)
            self.init_thread.start()
        except:
            pass
    
    def _init_camera(self):
        try:
            time.sleep(0.5)
            self.cap = cv2.VideoCapture(self.pipe_path, cv2.CAP_FFMPEG)
            if not self.cap.isOpened():
                self.initialized = True
                return
            
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            
            for i in range(2):
                ret, frame = self.cap.read()
                if ret and frame is not None and frame.size > 0:
                    with self.frame_lock:
                        self.frame = frame.copy()
                        self.last_valid_frame = frame.copy()
                    break
                time.sleep(0.02)
            
            self.available = True
            self.initialized = True
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
        except:
            self.available = False
            self.initialized = True
    
    def _read_loop(self):
        while self.running:
            try:
                if not self.cap or not self.cap.isOpened():
                    time.sleep(0.001)
                    continue
                
                ret, frame = self.cap.read()
                if not ret or frame is None or frame.size == 0:
                    continue
                
                with self.frame_lock:
                    self.frame = frame.copy()
                    self.last_valid_frame = frame.copy()
                
                self.frame_count += 1
                
                if time.time() - self.fps_start >= 0.5:
                    self.fps = int(self.frame_count / 0.5)
                    self.frame_count = 0
                    self.fps_start = time.time()
                    
            except:
                time.sleep(0.001)
    
    def get_frame(self):
        with self.frame_lock:
            if self.frame is not None:
                return self.frame.copy()
            return None
    
    def get_fps(self):
        return self.fps
    
    def is_available(self):
        return self.available and self.initialized
    
    def is_initialized(self):
        return self.initialized
    
    def stop(self):
        self.running = False
        if hasattr(self, 'thread') and self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        if self.cap:
            self.cap.release()
        if self.process:
            self.process.terminate()
        if os.path.exists(self.pipe_path):
            try:
                os.unlink(self.pipe_path)
            except:
                pass

# ============================================
# 🖐️ MediaPipe Setup
# ============================================
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    model_complexity=0,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.3
)

FINGER_MAP = {
    'left_pinky': 1, 'left_ring': 2, 'left_middle': 3,
    'left_index': 4, 'left_thumb': 5,
    'right_thumb': 6, 'right_index': 7,
    'right_middle': 8, 'right_ring': 9, 'right_pinky': 10
}

FINGER_STATE_CACHE = {}

def get_finger_states(hand_landmarks, is_left_hand):
    lm = hand_landmarks.landmark
    key_points = [(lm[4].x, lm[4].y), (lm[8].x, lm[8].y), (lm[12].x, lm[12].y), 
                  (lm[16].x, lm[16].y), (lm[20].x, lm[20].y)]
    cache_key = (is_left_hand, tuple(key_points))
    
    if cache_key in FINGER_STATE_CACHE:
        return FINGER_STATE_CACHE[cache_key].copy()
    
    finger_states = {}
    
    if is_left_hand:
        finger_states['left_thumb'] = lm[4].x > lm[3].x
        finger_states['left_index'] = lm[8].y < lm[6].y
        finger_states['left_middle'] = lm[12].y < lm[10].y
        finger_states['left_ring'] = lm[16].y < lm[14].y
        finger_states['left_pinky'] = lm[20].y < lm[18].y
    else:
        finger_states['right_thumb'] = lm[4].x < lm[3].x
        finger_states['right_index'] = lm[8].y < lm[6].y
        finger_states['right_middle'] = lm[12].y < lm[10].y
        finger_states['right_ring'] = lm[16].y < lm[14].y
        finger_states['right_pinky'] = lm[20].y < lm[18].y
    
    if len(FINGER_STATE_CACHE) > 50:
        FINGER_STATE_CACHE.clear()
    FINGER_STATE_CACHE[cache_key] = finger_states.copy()
    
    return finger_states

def get_hand_center(hand_landmarks):
    lm = hand_landmarks.landmark
    x = (lm[0].x + lm[5].x + lm[9].x + lm[13].x + lm[17].x) / 5
    y = (lm[0].y + lm[5].y + lm[9].y + lm[13].y + lm[17].y) / 5
    return x, y

def is_fist(finger_states, is_left):
    if is_left:
        fingers = ['left_thumb', 'left_index', 'left_middle', 'left_ring', 'left_pinky']
    else:
        fingers = ['right_thumb', 'right_index', 'right_middle', 'right_ring', 'right_pinky']
    extended_count = sum(1 for f in fingers if finger_states.get(f, False))
    return extended_count <= 1

# ============================================
# 🎵 Song Data
# ============================================

class PianoSheet:
    @staticmethod
    def get_song(song_name):
        songs = {
            'twinkle': {
                'name': 'Twinkle Twinkle Little Star',
                'key': 'C',
                'scale_notes': {
                    '1': 'C4', '2': 'D4', '3': 'E4', '4': 'F4', 
                    '5': 'G4', '6': 'A4', '7': 'B4'
                },
                'notes': [
                    ('1', 0.2), ('1', 0.2), ('5', 0.2), ('5', 0.2),
                    ('6', 0.2), ('6', 0.2), ('5', 0.2),
                    ('4', 0.2), ('4', 0.2), ('3', 0.2), ('3', 0.2),
                    ('2', 0.2), ('2', 0.2), ('1', 0.2),
                    ('5', 0.2), ('5', 0.2), ('4', 0.2), ('4', 0.2),
                    ('3', 0.2), ('3', 0.2), ('2', 0.2),
                    ('5', 0.2), ('5', 0.2), ('4', 0.2), ('4', 0.2),
                    ('3', 0.2), ('3', 0.2), ('2', 0.2),
                    ('1', 0.2), ('1', 0.2), ('5', 0.2), ('5', 0.2),
                    ('6', 0.2), ('6', 0.2), ('5', 0.2),
                    ('4', 0.2), ('4', 0.2), ('3', 0.2), ('3', 0.2),
                    ('2', 0.2), ('2', 0.2), ('1', 0.2)
                ]
            },
            'happy_birthday': {
                'name': 'Happy Birthday',
                'key': 'C',
                'scale_notes': {
                    '5': 'G4', '6': 'A4', '7': 'B4',
                    '1\'': 'C5', '2\'': 'D5', '3\'': 'E5', '4\'': 'F5'
                },
                'notes': [
                    ('5', 0.15), ('5', 0.15), ('6', 0.15), ('5', 0.15),
                    ('1\'', 0.15), ('7', 0.15),
                    ('5', 0.15), ('5', 0.15), ('6', 0.15), ('5', 0.15),
                    ('2\'', 0.15), ('1\'', 0.15),
                    ('5', 0.15), ('5', 0.15), ('5', 0.15), ('3\'', 0.15),
                    ('1\'', 0.15), ('7', 0.15), ('6', 0.15),
                    ('4\'', 0.15), ('4\'', 0.15), ('3\'', 0.15), ('1\'', 0.15),
                    ('2\'', 0.15), ('1\'', 0.15)
                ]
            },
            'jingle_bells': {
                'name': 'Jingle Bells',
                'key': 'C',
                'scale_notes': {
                    '1': 'C4', '2': 'D4', '3': 'E4', '4': 'F4', '5': 'G4'
                },
                'notes': [
                    ('3', 0.15), ('3', 0.15), ('3', 0.15),
                    ('3', 0.15), ('3', 0.15), ('3', 0.15),
                    ('3', 0.15), ('5', 0.15), ('1', 0.15), ('2', 0.15),
                    ('3', 0.15),
                    ('4', 0.15), ('4', 0.15), ('4', 0.15), ('4', 0.15),
                    ('4', 0.15), ('3', 0.15), ('3', 0.15), ('3', 0.15),
                    ('3', 0.15), ('2', 0.15), ('2', 0.15), ('3', 0.15),
                    ('2', 0.15), ('5', 0.15)
                ]
            },
            'ode_to_joy': {
                'name': 'Ode to Joy',
                'key': 'C',
                'scale_notes': {
                    '1': 'C4', '2': 'D4', '3': 'E4', '4': 'F4', '5': 'G4',
                    '1\'': 'C5', '2\'': 'D5', '3\'': 'E5', '4\'': 'F5', '5\'': 'G5',
                    '6\'': 'A5', '7\'': 'B5',
                    '1\'\'': 'C6'
                },
                'notes': [
                    # 第一乐句
                    ('3\'', 0.25), ('3\'', 0.25), ('4\'', 0.25), ('5\'', 0.25),
                    ('5\'', 0.25), ('4\'', 0.25), ('3\'', 0.25), ('2\'', 0.25),
                    ('1\'', 0.25), ('1\'', 0.25), ('2\'', 0.25), ('3\'', 0.25),
                    ('3\'', 0.25), ('2\'', 0.25), ('2\'', 0.5),
                    # 第二乐句
                    ('3\'', 0.25), ('3\'', 0.25), ('4\'', 0.25), ('5\'', 0.25),
                    ('5\'', 0.25), ('4\'', 0.25), ('3\'', 0.25), ('2\'', 0.25),
                    ('1\'', 0.25), ('1\'', 0.25), ('2\'', 0.25), ('3\'', 0.25),
                    ('2\'', 0.25), ('1\'', 0.25), ('1\'', 0.5),
                    # 第三乐句
                    ('2\'', 0.25), ('2\'', 0.25), ('3\'', 0.25), ('1\'', 0.25),
                    ('2\'', 0.25), ('4\'', 0.25), ('3\'', 0.25), ('1\'', 0.25),
                    ('2\'', 0.25), ('4\'', 0.25), ('3\'', 0.25), ('2\'', 0.25),
                    ('1\'', 0.25), ('2\'', 0.25), ('5', 0.5),
                    # 第四乐句（重复第一乐句）
                    ('3\'', 0.25), ('3\'', 0.25), ('4\'', 0.25), ('5\'', 0.25),
                    ('5\'', 0.25), ('4\'', 0.25), ('3\'', 0.25), ('2\'', 0.25),
                    ('1\'', 0.25), ('1\'', 0.25), ('2\'', 0.25), ('3\'', 0.25),
                    ('2\'', 0.25), ('1\'', 0.25), ('1\'', 0.5),
                ]
            },
            'moonlight': {
                'name': 'Moonlight Sonata',
                'key': 'C#m',
                'scale_notes': {
                    '3': 'E4', '5': 'G#4', '6': 'A4', '7': 'B4',
                    '1\'': 'C#5', '2\'': 'D#5', '3\'': 'E5'
                },
                'notes': [
                    ('3', 0.25), ('5', 0.25), ('7', 0.25), ('1\'', 0.25),
                    ('3\'', 0.25), ('1\'', 0.25), ('7', 0.25), ('5', 0.25),
                    ('3', 0.25), ('5', 0.25), ('7', 0.25), ('1\'', 0.25),
                    ('3\'', 0.25), ('1\'', 0.25), ('7', 0.25), ('6', 0.25),
                    ('3', 0.25), ('5', 0.25), ('7', 0.25), ('1\'', 0.25),
                    ('2\'', 0.25), ('1\'', 0.25), ('7', 0.25), ('6', 0.25),
                    ('5', 0.25), ('6', 0.25), ('7', 0.25), ('1\'', 0.25),
                    ('2\'', 0.25), ('3\'', 0.25), ('2\'', 0.25), ('1\'', 0.25)
                ]
            },
            'farewell': {
                'name': 'Farewell',
                'key': 'C',
                'scale_notes': {
                    '7̣': 'B3', '1': 'C4', '2': 'D4', '3': 'E4', '4': 'F4',
                    '5': 'G4', '6': 'A4', '7': 'B4',
                    '1\'': 'C5', '2\'': 'D5', '3\'': 'E5', '4\'': 'F5'
                },
                'notes': [
                    ('5', 0.2), ('3', 0.2), ('5', 0.2), ('1\'', 0.2), ('5', 0.2),
                    ('6', 0.2), ('1\'', 0.2), ('5', 0.2),
                    ('5', 0.2), ('1', 0.2), ('2', 0.2), ('3', 0.2), ('2', 0.2), ('1', 0.2),
                    ('2', 0.2),
                    ('5', 0.2), ('3', 0.2), ('5', 0.2), ('1\'', 0.15), ('7', 0.25),
                    ('6', 0.2), ('1\'', 0.2), ('5', 0.2),
                    ('5', 0.2), ('2', 0.2), ('3', 0.2), ('4', 0.15), ('7̣', 0.25),
                    ('1', 0.2),
                    ('6', 0.2), ('1\'', 0.2), ('1\'', 0.2),
                    ('7', 0.2), ('6', 0.2), ('7', 0.2), ('1\'', 0.2),
                    ('6', 0.2), ('7', 0.2), ('1\'', 0.2), ('6', 0.2), ('6', 0.2), ('5', 0.2), ('3', 0.2), ('1', 0.2),
                    ('2', 0.2),
                    ('5', 0.2), ('3', 0.2), ('5', 0.2), ('1\'', 0.15), ('7', 0.25),
                    ('6', 0.2), ('1\'', 0.2), ('5', 0.2),
                    ('5', 0.2), ('2', 0.2), ('3', 0.2), ('4', 0.15), ('7̣', 0.25),
                    ('1', 0.2)
                ]
            },
            'night_piano_5': {
                'name': 'Night Piano No.5',
                'key': 'C',
                'scale_notes': {
                    '1': 'C4', '2': 'D4', '3': 'E4', '4': 'F4', 
                    '5': 'G4', '6': 'A4', '7': 'B4',
                    'b3': 'Eb4', 'b7': 'Bb4',
                    '1\'': 'C5', '2\'': 'D5', '3\'': 'E5', '4\'': 'F5', 
                    '5\'': 'G5', '6\'': 'A5', '7\'': 'B5',
                    'b3\'': 'Eb5', 'b7\'': 'Bb5',
                    '1\'\'': 'C6', '2\'\'': 'D6', '3\'\'': 'E6', '4\'\'': 'F6', 
                    '5\'\'': 'G6', '6\'\'': 'A6', '7\'\'': 'B6',
                    'b3\'\'': 'Eb6', 'b7\'\'': 'Bb6',
                },
                'notes': [
                    ('1\'', 0.2), ('2\'', 0.2), ('b3\'', 0.2), ('5\'', 0.2), ('1\'\'', 0.6),
                    ('1\'', 0.2), ('2\'', 0.2), ('b3\'', 0.2), ('5\'', 0.2), ('1\'\'', 0.6),
                    ('4\'\'', 0.2), ('b3\'\'', 0.2), ('2\'\'', 0.2), ('3\'\'', 0.2), ('1\'\'', 0.8),
                    ('1\'', 0.2),
                    ('1\'', 0.2), ('2\'', 0.2), ('b3\'', 0.2), ('5\'', 0.2), ('1\'\'', 0.6),
                    ('1\'', 0.2), ('2\'', 0.2), ('b3\'', 0.2), ('5\'', 0.2), ('1\'\'', 0.6),
                    ('4\'\'', 0.2), ('b3\'\'', 0.2), ('2\'\'', 0.2), ('3\'\'', 0.2), ('1\'\'', 0.8),
                    ('5\'', 0.2), ('7\'', 0.2), ('1\'\'', 0.2), ('5\'\'', 0.2),
                    ('4\'\'', 0.2), ('5\'\'', 0.2), ('4\'\'', 0.2), ('5\'\'', 0.2), ('4\'\'', 0.2), ('b3\'\'', 0.2),
                    ('4\'\'', 0.2), ('4\'\'', 0.2), ('5\'\'', 0.2), ('b7\'\'', 0.2), ('5\'\'', 0.2),
                    ('b7\'', 0.2), ('5\'', 0.2), ('7\'', 0.2), ('5\'', 0.2), ('7\'', 0.2), ('4\'\'', 0.6),
                    ('b3\'\'', 0.2),
                    ('1\'', 0.2), ('2\'', 0.2), ('b3\'', 0.2), ('5\'', 0.2), ('1\'\'', 0.6),
                    ('5\'\'', 0.2), ('1\'\'', 0.2), ('4\'\'', 0.2), ('5\'\'', 0.2), ('4\'\'', 0.2),
                    ('2\'\'', 0.2), ('4\'\'', 0.2), ('b3\'\'', 0.2), ('2\'\'', 0.2), ('3\'\'', 0.2), ('1\'\'', 0.8),
                    ('b3\'', 0.2),
                    ('1\'', 0.2), ('2\'', 0.2), ('b3\'', 0.2), ('5\'', 0.2), ('1\'\'', 0.6),
                    ('1\'', 0.2), ('2\'', 0.2), ('b3\'', 0.2), ('5\'', 0.2), ('1\'\'', 0.6),
                    ('4\'\'', 0.2), ('b3\'\'', 0.2), ('4\'\'', 0.2), ('3\'\'', 0.2), ('1\'\'', 0.8),
                ]
            }
        }
        return songs.get(song_name, songs['twinkle'])
    
    @staticmethod
    def get_song_list():
        return [
            {'id': 'twinkle', 'name': 'Twinkle Twinkle Little Star'},
            {'id': 'happy_birthday', 'name': 'Happy Birthday'},
            {'id': 'jingle_bells', 'name': 'Jingle Bells'},
            {'id': 'farewell', 'name': 'Farewell'},
            {'id': 'ode_to_joy', 'name': 'Ode to Joy'},
            {'id': 'moonlight', 'name': 'Moonlight Sonata'},
            {'id': 'night_piano_5', 'name': 'Night Piano No.5'}
        ]

def preload_all_samples():
    """预加载所有88个钢琴采样到缓存，显示Loading动画（连续丝滑版）"""
    print("🎵 预加载所有钢琴采样...")
    
    # 创建Loading画面 - 静态部分
    loading_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    
    # 使用背景图片或纯色背景
    if 'main' in bg_images:
        loading_surface.blit(bg_images['main'], (0, 0))
    else:
        loading_surface.fill((20, 20, 40))
    
    # 半透明遮罩
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    overlay.set_alpha(160)
    overlay.fill(BLACK)
    loading_surface.blit(overlay, (0, 0))
    
    # 加载文字 - 使用等宽字体
    loading_font = FONT_MONO_XLARGE if MONO_FONT_PATH else FONT_XLARGE
    loading_text = get_prerendered_text(loading_font, "Loading...", WHITE)
    loading_rect = loading_text.get_rect(center=(SCREEN_WIDTH//2, SCREEN_HEIGHT//2 - 100))
    
    # 文字阴影
    loading_shadow = get_prerendered_text(loading_font, "Loading...", BLACK)
    shadow_rect = loading_rect.copy()
    shadow_rect.x += 4
    shadow_rect.y += 4
    
    # 进度条参数
    bar_width = 500
    bar_height = 20
    bar_x = SCREEN_WIDTH//2 - bar_width//2
    bar_y = SCREEN_HEIGHT//2 + 20
    
    # 进度条背景
    bar_bg_rect = pygame.Rect(bar_x, bar_y, bar_width, bar_height)
    draw_rounded_rect_aa(loading_surface, (60, 60, 80), bar_bg_rect, 10)
    
    # 百分比文字位置
    percent_font = FONT_MONO_LARGE if MONO_FONT_PATH else FONT_LARGE
    
    # 显示第一帧
    screen.blit(loading_surface, (0, 0))
    pygame.display.flip()
    
    loaded_count = 0
    total = len(NOTE_NAMES_88)
    
    # 连续进度变量
    smooth_progress = 0.0
    target_progress = 0.0
    
    # 用于闪烁效果的计时器
    frame_counter = 0
    
    # 缓存进度条填充表面（按不同宽度缓存）
    bar_fill_cache = {}
    # 缓存发光表面
    glow_cache = {}
    
    # 预创建发光表面缓存
    def get_glow_surface(radius):
        cache_key = radius
        if cache_key in glow_cache:
            return glow_cache[cache_key]
        
        glow_surface = pygame.Surface((radius * 2 + 20, radius * 2 + 20), pygame.SRCALPHA)
        for r in range(radius, 0, -2):
            alpha = int(40 * (1 - r / radius))
            color = (100, 200, 255, alpha)
            pygame.draw.circle(glow_surface, color, (radius + 10, radius + 10), r)
        
        glow_cache[cache_key] = glow_surface
        return glow_surface
    
    # 主循环
    for i, note in enumerate(NOTE_NAMES_88):
        try:
            # 加载中等力度层
            cache_key = f"{note}_8"
            if cache_key not in SAMPLE_SOUND_CACHE:
                filepath = get_sample_file_for_note(note)
                if filepath is not None:
                    sound = pygame.mixer.Sound(filepath)
                    SAMPLE_SOUND_CACHE[cache_key] = sound
                    loaded_count += 1
            
            # 预加载其他力度层
            for vel in [4, 12, 16]:
                cache_key = f"{note}_{vel}"
                if cache_key not in SAMPLE_SOUND_CACHE:
                    filepath = get_sample_file_for_note(note)
                    if filepath is not None:
                        sound = pygame.mixer.Sound(filepath)
                        SAMPLE_SOUND_CACHE[cache_key] = sound
                        
        except Exception as e:
            print(f"  ❌ 预加载音符 {note} 失败: {e}")
        
        # 更新目标进度
        target_progress = (i + 1) / total
        
        frame_counter += 1
        
        # 每帧都更新，让进度条连续丝滑
        # 复制主表面
        temp_surface = loading_surface.copy()
        
        # 平滑插值进度 - 每次向目标靠近
        smooth_progress = smooth_progress + (target_progress - smooth_progress) * 0.15
        # 如果非常接近目标，直接设为目标值
        if abs(smooth_progress - target_progress) < 0.001:
            smooth_progress = target_progress
        
        # 计算进度条宽度
        progress_width = int(bar_width * smooth_progress)
        
        # 进度条填充 - 使用缓存
        if progress_width > 0:
            cache_key = int(progress_width / 5)
            if cache_key not in bar_fill_cache:
                bar_fill_surface = pygame.Surface((progress_width, bar_height), pygame.SRCALPHA)
                draw_rounded_rect_aa(bar_fill_surface, (100, 200, 255), 
                                   (0, 0, progress_width, bar_height), 10)
                # 添加内部高光（确保宽度足够）
                if progress_width > 12:
                    highlight_height = max(2, bar_height // 3)
                    highlight_width = progress_width - 8
                    if highlight_width > 0 and highlight_height > 0:
                        highlight_surface = pygame.Surface((highlight_width, highlight_height), pygame.SRCALPHA)
                        highlight_surface.fill((200, 255, 255, 60))
                        bar_fill_surface.blit(highlight_surface, (4, 3))
                bar_fill_cache[cache_key] = bar_fill_surface
            temp_surface.blit(bar_fill_cache[cache_key], (bar_x, bar_y))
        
        # 百分比文字 - 显示平滑进度
        percent_text = get_prerendered_text(percent_font, f"{int(smooth_progress * 100)}%", WHITE)
        percent_rect = percent_text.get_rect(center=(SCREEN_WIDTH//2, bar_y + bar_height + 45))
        temp_surface.blit(percent_text, percent_rect)
        
        # 加载文字 - 连续闪烁效果（使用正弦波）
        blink_alpha = int(128 + 127 * math.sin(frame_counter * 0.05))
        loading_shadow.set_alpha(blink_alpha // 2)
        loading_text.set_alpha(blink_alpha)
        
        temp_surface.blit(loading_shadow, shadow_rect)
        temp_surface.blit(loading_text, loading_rect)
        
        # 进度条末端光效 - 使用缓存
        if progress_width > 5:
            glow_radius = int(10 + 4 * math.sin(frame_counter * 0.06))
            glow_x = bar_x + progress_width
            glow_y = bar_y + bar_height // 2
            
            # 使用缓存的发光表面
            glow_surface = get_glow_surface(glow_radius)
            temp_surface.blit(glow_surface, (glow_x - glow_radius - 10, glow_y - glow_radius - 10))
        
        screen.blit(temp_surface, (0, 0))
        pygame.display.flip()
        
        # 处理事件，防止卡死
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
        
        # 每帧都稍微延迟，控制帧率
        time.sleep(0.002)
    
    # 最终显示100%
    temp_surface = loading_surface.copy()
    progress_width = bar_width
    bar_fill_rect = pygame.Rect(bar_x, bar_y, progress_width, bar_height)
    draw_rounded_rect_aa(temp_surface, (100, 200, 255), bar_fill_rect, 10)
    
    # 添加最终高光
    if progress_width > 12:
        highlight_height = max(2, bar_height // 3)
        highlight_width = progress_width - 8
        if highlight_width > 0 and highlight_height > 0:
            highlight_surface = pygame.Surface((highlight_width, highlight_height), pygame.SRCALPHA)
            highlight_surface.fill((200, 255, 255, 80))
            temp_surface.blit(highlight_surface, (bar_x + 4, bar_y + 3))
    
    percent_text = get_prerendered_text(percent_font, "100%", WHITE)
    percent_rect = percent_text.get_rect(center=(SCREEN_WIDTH//2, bar_y + bar_height + 45))
    temp_surface.blit(percent_text, percent_rect)
    
    loading_text.set_alpha(255)
    loading_shadow.set_alpha(128)
    temp_surface.blit(loading_shadow, shadow_rect)
    temp_surface.blit(loading_text, loading_rect)
    
    # 最终完成光效
    glow_surface = get_glow_surface(16)
    temp_surface.blit(glow_surface, (bar_x + bar_width - 26, bar_y + bar_height//2 - 26))
    
    screen.blit(temp_surface, (0, 0))
    pygame.display.flip()
    time.sleep(0.2)
    
    print(f"✅ 预加载完成 (加载了 {loaded_count} 个采样)")

def preload_song_sounds(scale_notes):
    """预加载歌曲所有音符声音到缓存 - 不播放（已全局预加载，此函数仅用于显示）"""
    pass

print("🎹 使用88键钢琴采样:")
print(f"📁 采样目录: {SAMPLES_DIR}")

if os.path.exists(SAMPLES_DIR):
    sample_files = glob.glob(os.path.join(SAMPLES_DIR, "tone*.wav"))
    print(f"✅ 找到 {len(sample_files)} 个 WAV 采样文件")
    print(f"🎵 音频通道数: {pygame.mixer.get_num_channels()}")
    print(f"🎹 88键映射: {NOTE_NAMES_88[0]} ... {NOTE_NAMES_88[-1]}")
else:
    print(f"⚠️ 采样目录不存在: {SAMPLES_DIR}")

# ============================================
# 🎮 Menu System
# ============================================

class Menu:
    def __init__(self, width, height, bg_images):
        self.width = width
        self.height = height
        self.scale = min(width, height) / 1080
        self.bg_images = bg_images
        
        self.button_cache = {}
        
        self.options = [
            {"label": "Start Game", "action": "start"},
            {"label": "Auto Demo", "action": "demo"},
            {"label": "Quit", "action": "quit"}
        ]
        self.pause_options = [
            {"label": "Resume", "action": "resume"},
            {"label": "Quit to Menu", "action": "quit_menu"}
        ]
        
        self.difficulty_options = [
            {"label": "Easy", "action": "easy", "speed": 0.5},
            {"label": "Normal", "action": "normal", "speed": 0.8},
            {"label": "Hard", "action": "hard", "speed": 1.3}
        ]
        
        self.song_list = PianoSheet.get_song_list()
        self.song_selection = 0
        self.difficulty_selection = 1
        self.show_song_menu = False
        self.show_difficulty_menu = False
        self.show_main_menu = True
        self.hover_index = -1
        self.click_cooldown = 0
        self.mouse_x = width // 2
        self.mouse_y = height // 2
        self.is_clicking = False
        self.visible = True
        self.is_pause_menu = False
        self.scroll_offset = 0
        self.max_visible = 7
        self.is_demo_mode = False
        self.selected_song_id = None
        
        self.overlay_cache = {}
        
    def set_visible(self, visible):
        self.visible = visible
        
    def set_pause_menu(self, is_pause):
        self.is_pause_menu = is_pause
        self.show_song_menu = False
        self.show_difficulty_menu = False
        self.show_main_menu = False
        self.hover_index = -1
        
    def show_main(self):
        self.show_main_menu = True
        self.show_song_menu = False
        self.show_difficulty_menu = False
        self.hover_index = -1
        
    def update(self, mouse_x, mouse_y, is_clicking):
        if not self.visible:
            return None
            
        self.mouse_x = mouse_x
        self.mouse_y = mouse_y
        self.is_clicking = is_clicking
        
        if self.click_cooldown > 0:
            self.click_cooldown -= 1
        
        self.hover_index = -1
        
        if self.show_difficulty_menu:
            start_y = self.height // 2 - int(80 * self.scale)
            item_height = int(100 * self.scale)
            
            for i in range(len(self.difficulty_options)):
                y = start_y + i * item_height
                text_width = int(500 * self.scale)
                text_height = int(80 * self.scale)
                x = self.width // 2 - text_width // 2
                
                if x <= mouse_x <= x + text_width and y <= mouse_y <= y + text_height:
                    self.hover_index = i
                    break
            
            back_x = self.width // 2 - int(160 * self.scale)
            back_y = start_y + len(self.difficulty_options) * item_height + int(60 * self.scale)
            back_width = int(320 * self.scale)
            back_height = int(80 * self.scale)
            if back_x <= mouse_x <= back_x + back_width and back_y <= mouse_y <= back_y + back_height:
                self.hover_index = -2
                
        elif self.show_song_menu:
            start_y = int(240 * self.scale)
            item_height = int(90 * self.scale)
            max_items = len(self.song_list)
            visible_items = min(self.max_visible, max_items)
            
            for i in range(visible_items):
                idx = i + self.scroll_offset
                if idx >= max_items:
                    break
                    
                y = start_y + i * item_height
                text_width = int(900 * self.scale)
                text_height = int(72 * self.scale)
                x = self.width // 2 - text_width // 2
                
                if x <= mouse_x <= x + text_width and y <= mouse_y <= y + text_height:
                    self.hover_index = idx
                    break
            
            back_x = self.width // 2 - int(160 * self.scale)
            back_y = start_y + visible_items * item_height + int(60 * self.scale)
            back_width = int(320 * self.scale)
            back_height = int(80 * self.scale)
            if back_x <= mouse_x <= back_x + back_width and back_y <= mouse_y <= back_y + back_height:
                self.hover_index = -2
                
        elif self.show_main_menu:
            start_y = self.height // 2 - int(60 * self.scale)
            for i in range(len(self.options)):
                y = start_y + i * int(130 * self.scale)
                text_width = int(600 * self.scale)
                text_height = int(100 * self.scale)
                x = self.width // 2 - text_width // 2
                if x <= mouse_x <= x + text_width and y <= mouse_y <= y + text_height:
                    self.hover_index = i
                    break
        else:
            start_y = self.height // 2 - int(80 * self.scale)
            for i in range(len(self.pause_options)):
                y = start_y + i * int(130 * self.scale)
                text_width = int(600 * self.scale)
                text_height = int(95 * self.scale)
                x = self.width // 2 - text_width // 2
                if x <= mouse_x <= x + text_width and y <= mouse_y <= y + text_height:
                    self.hover_index = i
                    break
        
        if is_clicking and self.click_cooldown == 0:
            self.click_cooldown = 15
            
            if self.show_difficulty_menu:
                if self.hover_index >= 0:
                    difficulty = self.difficulty_options[self.hover_index]
                    self.difficulty_selection = self.hover_index
                    self.show_difficulty_menu = False
                    self.show_song_menu = False
                    self.show_main_menu = False
                    return {
                        "action": "start_game", 
                        "song": self.selected_song_id,
                        "difficulty": difficulty["action"],
                        "speed": difficulty["speed"]
                    }
                elif self.hover_index == -2:
                    self.show_difficulty_menu = False
                    self.show_song_menu = True
                    self.show_main_menu = False
                    return None
                    
            elif self.show_song_menu:
                if self.hover_index >= 0:
                    self.song_selection = self.hover_index
                    self.selected_song_id = self.song_list[self.song_selection]['id']
                    if self.is_demo_mode:
                        self.show_song_menu = False
                        self.show_difficulty_menu = False
                        self.show_main_menu = False
                        return {
                            "action": "demo",
                            "song": self.selected_song_id,
                            "speed": 0.8
                        }
                    else:
                        self.show_song_menu = False
                        self.show_difficulty_menu = True
                        self.hover_index = -1
                        return None
                elif self.hover_index == -2:
                    self.show_song_menu = False
                    self.show_main_menu = True
                    self.is_demo_mode = False
                    return {"action": "back"}
            elif self.show_main_menu:
                if self.hover_index >= 0:
                    action = self.options[self.hover_index]["action"]
                    if action in ("start", "demo"):
                        self.show_song_menu = True
                        self.show_main_menu = False
                        self.is_demo_mode = (action == "demo")
                        self.show_difficulty_menu = False
                        return None
                    else:
                        return {"action": action}
            else:
                if self.hover_index >= 0:
                    return {"action": self.pause_options[self.hover_index]["action"]}
        return None
    
    def _get_button_surface(self, text, width, height, hover, color=None):
        if color is None:
            color = WHITE
            
        cache_key = (text, width, height, hover, color[0], color[1], color[2])
        if cache_key in self.button_cache:
            return self.button_cache[cache_key].copy()
        
        button = pygame.Surface((width, height), pygame.SRCALPHA)
        border_radius = 18
        
        if hover:
            bg_color = (60, 60, 30, 220)
            text_color = YELLOW
            
            draw_rounded_rect_aa(button, bg_color, (0, 0, width, height), border_radius)
            highlight_color = (255, 255, 0, 220)
            draw_rounded_rect_aa(button, highlight_color, (0, 0, width, height), border_radius, border_width=4)
            inner_glow_color = (255, 255, 100, 40)
            inner_rect = (4, 4, width - 8, height - 8)
            draw_rounded_rect_aa(button, inner_glow_color, inner_rect, max(0, border_radius - 2))
            
            outer_glow = pygame.Surface((width, height), pygame.SRCALPHA)
            draw_rounded_rect_aa(outer_glow, (255, 255, 0, 15), (0, 0, width, height), border_radius + 2)
            button.blit(outer_glow, (0, 0))
            
        else:
            bg_color = (0, 0, 0, 200)
            border_color = GRAY
            text_color = color
            
            draw_rounded_rect_aa(button, bg_color, (0, 0, width, height), border_radius)
            draw_rounded_rect_aa(button, border_color, (0, 0, width, height), border_radius, border_width=3)
        
        font_size = int(56 * self.scale)
        if MONO_FONT_PATH:
            font = pygame.font.Font(MONO_FONT_PATH, font_size)
        else:
            font = pygame.font.Font(None, font_size)
            
        text_surface = get_prerendered_text(font, text, text_color)
        text_rect = text_surface.get_rect(center=(width // 2, height // 2))
        button.blit(text_surface, text_rect)
        
        if len(self.button_cache) > 30:
            self.button_cache.clear()
        self.button_cache[cache_key] = button.copy()
        
        return button
    
    def draw_button(self, surface, text, x, y, width, height, hover, color=None):
        button = self._get_button_surface(text, width, height, hover, color)
        surface.blit(button, (int(x), int(y)))
    
    def draw(self, surface):
        if not self.visible:
            return
        
        if self.show_difficulty_menu:
            if 'song' in self.bg_images:
                surface.blit(self.bg_images['song'], (0, 0))
            
            overlay_key = ('difficulty', self.width, self.height)
            if overlay_key not in self.overlay_cache:
                overlay = pygame.Surface((self.width, self.height))
                overlay.set_alpha(120)
                overlay.fill(BLACK)
                self.overlay_cache[overlay_key] = overlay
            surface.blit(self.overlay_cache[overlay_key], (0, 0))
            
            title_text = get_prerendered_text(FONT_XLARGE, "Select Difficulty", YELLOW)
            title_shadow = get_prerendered_text(FONT_XLARGE, "Select Difficulty", BLACK)
            title_rect = title_text.get_rect(center=(self.width // 2, int(140 * self.scale)))
            surface.blit(title_shadow, (title_rect.x + 3, title_rect.y + 3))
            surface.blit(title_text, title_rect)
            
            song_name = ""
            for s in self.song_list:
                if s['id'] == self.selected_song_id:
                    song_name = s['name']
                    break
            if song_name:
                song_text = get_prerendered_text(FONT_MEDIUM, f"Song: {song_name}", WHITE)
                bg_width = song_text.get_width() + 60
                bg_height = song_text.get_height() + 30
                bg_x = self.width // 2 - bg_width // 2
                bg_y = int(210 * self.scale) - 15
                bg_rect = pygame.Rect(bg_x, bg_y, bg_width, bg_height)
                draw_rounded_rect_alpha(surface, (0, 0, 0, 200), bg_rect, 12)
                
                song_rect = song_text.get_rect(center=(self.width // 2, int(210 * self.scale) + 15))
                surface.blit(song_text, song_rect)
            
            start_y = self.height // 2 - int(80 * self.scale)
            
            for i, option in enumerate(self.difficulty_options):
                y = start_y + i * int(100 * self.scale)
                text_width = int(500 * self.scale)
                text_height = int(80 * self.scale)
                x = self.width // 2 - text_width // 2
                
                hover = (i == self.hover_index)
                button = self._get_button_surface(option["label"], text_width, text_height, hover)
                surface.blit(button, (int(x), int(y)))
            
            back_y = start_y + len(self.difficulty_options) * int(100 * self.scale) + int(60 * self.scale)
            back_x = self.width // 2 - int(160 * self.scale)
            self.draw_button(surface, "Back", back_x, back_y, int(320 * self.scale), int(80 * self.scale), self.hover_index == -2)
        
        elif self.show_song_menu:
            if 'song' in self.bg_images:
                surface.blit(self.bg_images['song'], (0, 0))
            
            overlay_key = ('song', self.width, self.height)
            if overlay_key not in self.overlay_cache:
                overlay = pygame.Surface((self.width, self.height))
                overlay.set_alpha(120)
                overlay.fill(BLACK)
                self.overlay_cache[overlay_key] = overlay
            surface.blit(self.overlay_cache[overlay_key], (0, 0))
            
            title_text = get_prerendered_text(FONT_XLARGE, "Select Song", YELLOW)
            title_shadow = get_prerendered_text(FONT_XLARGE, "Select Song", BLACK)
            title_rect = title_text.get_rect(center=(self.width // 2, int(110 * self.scale)))
            surface.blit(title_shadow, (title_rect.x + 3, title_rect.y + 3))
            surface.blit(title_text, title_rect)
            
            start_y = int(240 * self.scale)
            item_height = int(90 * self.scale)
            visible_items = min(self.max_visible, len(self.song_list))
            
            for i in range(visible_items):
                idx = i + self.scroll_offset
                if idx >= len(self.song_list):
                    break
                    
                y = start_y + i * item_height
                text_width = int(900 * self.scale)
                text_height = int(72 * self.scale)
                x = self.width // 2 - text_width // 2
                
                song = self.song_list[idx]
                hover = (idx == self.hover_index)
                
                border_radius = 14
                
                if hover:
                    bg_color = (255, 255, 0, 60)
                    border_color = YELLOW
                    text_color = YELLOW
                else:
                    bg_color = (0, 0, 0, 180)
                    border_color = (60, 60, 80)
                    text_color = (200, 200, 200)
                
                draw_rounded_rect_alpha(surface, bg_color, (x, y, text_width, text_height), border_radius)
                
                if hover:
                    draw_rounded_rect_alpha(surface, (0, 0, 0, 0), (x, y, text_width, text_height),
                                          border_radius, border_width=3, border_color_alpha=border_color)
                
                font_size = int(44 * self.scale)
                if MONO_FONT_PATH:
                    font = pygame.font.Font(MONO_FONT_PATH, font_size)
                else:
                    font = pygame.font.Font(None, font_size)
                
                text_surface = get_prerendered_text(font, song['name'], text_color)
                text_rect = text_surface.get_rect(center=(self.width // 2, y + text_height // 2))
                surface.blit(text_surface, text_rect)
            
            back_y = start_y + visible_items * item_height + int(60 * self.scale)
            back_x = self.width // 2 - int(160 * self.scale)
            self.draw_button(surface, "Back", back_x, back_y, int(320 * self.scale), int(80 * self.scale), self.hover_index == -2)
        
        elif self.show_main_menu:
            if 'main' in self.bg_images:
                surface.blit(self.bg_images['main'], (0, 0))
            
            overlay_key = ('main', self.width, self.height)
            if overlay_key not in self.overlay_cache:
                overlay = pygame.Surface((self.width, self.height))
                overlay.set_alpha(100)
                overlay.fill(BLACK)
                self.overlay_cache[overlay_key] = overlay
            surface.blit(self.overlay_cache[overlay_key], (0, 0))
            
            title_text = get_prerendered_text(FONT_XLARGE, "Gesture Rhythm Master", YELLOW)
            title_shadow = get_prerendered_text(FONT_XLARGE, "Gesture Rhythm Master", BLACK)
            title_rect = title_text.get_rect(center=(self.width // 2, int(180 * self.scale)))
            surface.blit(title_shadow, (title_rect.x + 3, title_rect.y + 3))
            surface.blit(title_text, title_rect)
            
            start_y = self.height // 2 - int(60 * self.scale)
            for i, option in enumerate(self.options):
                y = start_y + i * int(130 * self.scale)
                text_width = int(600 * self.scale)
                text_height = int(100 * self.scale)
                x = self.width // 2 - text_width // 2
                self.draw_button(surface, option["label"], x, y, text_width, text_height, i == self.hover_index)
        
        else:
            if 'pause' in self.bg_images:
                surface.blit(self.bg_images['pause'], (0, 0))
            
            overlay_key = ('pause', self.width, self.height)
            if overlay_key not in self.overlay_cache:
                overlay = pygame.Surface((self.width, self.height))
                overlay.set_alpha(140)
                overlay.fill(BLACK)
                self.overlay_cache[overlay_key] = overlay
            surface.blit(self.overlay_cache[overlay_key], (0, 0))
            
            title_text = get_prerendered_text(FONT_XLARGE, "PAUSED", YELLOW)
            title_shadow = get_prerendered_text(FONT_XLARGE, "PAUSED", BLACK)
            title_rect = title_text.get_rect(center=(self.width // 2, int(140 * self.scale)))
            surface.blit(title_shadow, (title_rect.x + 3, title_rect.y + 3))
            surface.blit(title_text, title_rect)
            
            start_y = self.height // 2 - int(60 * self.scale)
            for i, option in enumerate(self.pause_options):
                y = start_y + i * int(130 * self.scale)
                text_width = int(600 * self.scale)
                text_height = int(95 * self.scale)
                x = self.width // 2 - text_width // 2
                self.draw_button(surface, option["label"], x, y, text_width, text_height, i == self.hover_index)

# ============================================
# 📊 Result Screen
# ============================================

class ResultScreen:
    def __init__(self, width, height, bg_images):
        self.width = width
        self.height = height
        self.scale = min(width, height) / 1080        
        self.bg_images = bg_images
        self.visible = False
        self.stats = {}
        self.rating = ""
        self.rating_color = WHITE
        self.rating_description = ""
        self.hover_index = -1
        self.click_cooldown = 0
        self.mouse_x = width // 2
        self.mouse_y = height // 2
        self.is_demo = False
        self.button_width = int(550 * self.scale)
        self.button_height = int(85 * self.scale)
        
        self.button_cache = {}
        self.overlay_cache = {}
        
        self.options = [
            {"label": "Play Again", "action": "retry"},
            {"label": "Back to Menu", "action": "menu"}
        ]
        
    def show(self, stats, is_demo=False):
        self.visible = True
        self.stats = stats
        self.is_demo = is_demo
        if not is_demo:
            self.calculate_rating()
        else:
            self.rating = "DEMO"
            self.rating_color = CYAN
            self.rating_description = "Auto Demo Completed!"
        self.hover_index = -1
        self.click_cooldown = 15
        self.button_cache.clear()
        
    def hide(self):
        self.visible = False
        
    def calculate_rating(self):
        total = self.stats.get('perfect', 0) + self.stats.get('good', 0) + self.stats.get('miss', 0)
        if total == 0:
            self.rating = "No Data"
            self.rating_color = GRAY
            self.rating_description = "No notes played"
            return
        
        miss_count = self.stats.get('miss', 0)
        miss_rate = miss_count / total
        perfect_rate = self.stats.get('perfect', 0) / total
        
        if miss_rate == 0:
            if perfect_rate >= 0.95:
                self.rating = "SSS+"
                self.rating_color = GOLD
                self.rating_description = "Perfect Full Combo!"
            elif perfect_rate >= 0.85:
                self.rating = "SSS"
                self.rating_color = GOLD
                self.rating_description = "Excellent Full Combo!"
            elif perfect_rate >= 0.70:
                self.rating = "SS"
                self.rating_color = SILVER
                self.rating_description = "Great Full Combo!"
            else:
                self.rating = "S"
                self.rating_color = (255, 215, 0)
                self.rating_description = "Good Full Combo!"
        elif miss_rate <= 0.02:
            self.rating = "S+"
            self.rating_color = GOLD
            self.rating_description = "Almost Perfect!"
        elif miss_rate <= 0.05:
            self.rating = "S"
            self.rating_color = GOLD
            self.rating_description = "Excellent!"
        elif miss_rate <= 0.10:
            self.rating = "A"
            self.rating_color = GREEN
            self.rating_description = "Great!"
        elif miss_rate <= 0.15:
            self.rating = "B"
            self.rating_color = CYAN
            self.rating_description = "Good!"
        elif miss_rate <= 0.25:
            self.rating = "C"
            self.rating_color = BLUE
            self.rating_description = "Fair"
        elif miss_rate <= 0.40:
            self.rating = "D"
            self.rating_color = ORANGE
            self.rating_description = "Needs Practice"
        else:
            self.rating = "F"
            self.rating_color = RED
            self.rating_description = "Keep Trying!"
            
    def _get_button_surface(self, text, width, height, hover, color=WHITE):
        cache_key = (text, width, height, hover, color[0], color[1], color[2])
        if cache_key in self.button_cache:
            return self.button_cache[cache_key].copy()
        
        button = pygame.Surface((width, height), pygame.SRCALPHA)
        border_radius = 18
        
        if hover:
            bg_color = (60, 60, 30, 220)
            text_color = YELLOW
            
            draw_rounded_rect_aa(button, bg_color, (0, 0, width, height), border_radius)
            highlight_color = (255, 255, 0, 220)
            draw_rounded_rect_aa(button, highlight_color, (0, 0, width, height), border_radius, border_width=4)
            inner_glow_color = (255, 255, 100, 40)
            inner_rect = (4, 4, width - 8, height - 8)
            draw_rounded_rect_aa(button, inner_glow_color, inner_rect, max(0, border_radius - 2))
            
            outer_glow = pygame.Surface((width, height), pygame.SRCALPHA)
            draw_rounded_rect_aa(outer_glow, (255, 255, 0, 15), (0, 0, width, height), border_radius + 2)
            button.blit(outer_glow, (0, 0))
            
        else:
            bg_color = (0, 0, 0, 200)
            border_color = GRAY
            text_color = color
            
            draw_rounded_rect_aa(button, bg_color, (0, 0, width, height), border_radius)
            draw_rounded_rect_aa(button, border_color, (0, 0, width, height), border_radius, border_width=3)
        
        font_size = int(56 * self.scale)
        if MONO_FONT_PATH:
            font = pygame.font.Font(MONO_FONT_PATH, font_size)
        else:
            font = pygame.font.Font(None, font_size)
        
        text_surface = get_prerendered_text(font, text, text_color)
        text_rect = text_surface.get_rect(center=(width // 2, height // 2))
        button.blit(text_surface, text_rect)
        
        if len(self.button_cache) > 20:
            self.button_cache.clear()
        self.button_cache[cache_key] = button.copy()
        
        return button
        
    def draw_button(self, surface, text, x, y, width, height, hover, color=WHITE):
        button = self._get_button_surface(text, width, height, hover, color)
        surface.blit(button, (int(x), int(y)))
        
    def get_button_position(self, index):
        total = self.stats.get('perfect', 0) + self.stats.get('good', 0) + self.stats.get('miss', 0)
        if total > 0:
            num_stats_rows = 3
        else:
            num_stats_rows = 0
        
        if self.is_demo:
            button_start_y = int(460 * self.scale)
        elif num_stats_rows > 0:
            button_start_y = int(460 * self.scale) + num_stats_rows * int(70 * self.scale)
        else:
            button_start_y = int(460 * self.scale)
        
        x = self.width // 2 - self.button_width // 2
        y = button_start_y + index * int(120 * self.scale)
        return x, y, self.button_width, self.button_height
        
    def update(self, mouse_x, mouse_y, is_clicking):
        if not self.visible:
            return None
            
        self.mouse_x = mouse_x
        self.mouse_y = mouse_y
        
        if self.click_cooldown > 0:
            self.click_cooldown -= 1
            
        self.hover_index = -1
        
        for i in range(len(self.options)):
            x, y, w, h = self.get_button_position(i)
            if x <= mouse_x <= x + w and y <= mouse_y <= y + h:
                self.hover_index = i
                break
                
        if is_clicking and self.click_cooldown == 0:
            self.click_cooldown = 15
            if self.hover_index >= 0:
                return {"action": self.options[self.hover_index]["action"]}
                
        return None
        
    def draw(self, surface):
        if not self.visible:
            return
        
        if 'result' in self.bg_images:
            surface.blit(self.bg_images['result'], (0, 0))
        
        overlay_key = ('result', self.width, self.height, self.is_demo)
        if overlay_key not in self.overlay_cache:
            overlay = pygame.Surface((self.width, self.height))
            overlay.set_alpha(150)
            overlay.fill(BLACK)
            self.overlay_cache[overlay_key] = overlay
        surface.blit(self.overlay_cache[overlay_key], (0, 0))
        
        if self.is_demo:
            title_text = get_prerendered_text(FONT_XLARGE, "Demo Complete!", CYAN)
            title_shadow = get_prerendered_text(FONT_XLARGE, "Demo Complete!", BLACK)
        else:
            title_text = get_prerendered_text(FONT_XLARGE, "Song Complete!", YELLOW)
            title_shadow = get_prerendered_text(FONT_XLARGE, "Song Complete!", BLACK)
        title_rect = title_text.get_rect(center=(self.width // 2, int(150 * self.scale)))
        surface.blit(title_shadow, (title_rect.x + 3, title_rect.y + 3))
        surface.blit(title_text, title_rect)
        
        rating_font = pygame.font.Font(None, int(130 * self.scale))
        rating_text = get_prerendered_text(rating_font, self.rating, self.rating_color)
        rating_shadow = get_prerendered_text(rating_font, self.rating, BLACK)
        rating_rect = rating_text.get_rect(center=(self.width // 2, int(260 * self.scale)))
        surface.blit(rating_shadow, (rating_rect.x + 3, rating_rect.y + 3))
        surface.blit(rating_text, rating_rect)
        
        if not self.is_demo:
            desc_text = get_prerendered_text(FONT_MEDIUM, self.rating_description, self.rating_color)
            desc_shadow = get_prerendered_text(FONT_MEDIUM, self.rating_description, BLACK)
            desc_rect = desc_text.get_rect(center=(self.width // 2, int(320 * self.scale)))
            surface.blit(desc_shadow, (desc_rect.x + 2, desc_rect.y + 2))
            surface.blit(desc_text, desc_rect)
        
        if not self.is_demo:
            total = self.stats.get('perfect', 0) + self.stats.get('good', 0) + self.stats.get('miss', 0)
            if total > 0:
                stats_data = [
                    ("Score", str(self.stats.get('score', 0)), WHITE),
                    ("Perfect", str(self.stats.get('perfect', 0)), GREEN),
                    ("Good", str(self.stats.get('good', 0)), CYAN),
                    ("Miss", str(self.stats.get('miss', 0)), RED),
                    ("Max Combo", str(self.stats.get('max_combo', 0)), YELLOW),
                    ("Accuracy", f"{self.stats.get('accuracy', 0):.1f}%", GRAY),
                ]
                
                col_width = int(520 * self.scale)
                gap_between_cols = int(60 * self.scale)
                total_width = col_width * 2 + gap_between_cols
                start_x = (self.width - total_width) // 2
                start_y = int(370 * self.scale)
                row_height = int(70 * self.scale)
                
                for i, (label, value, color) in enumerate(stats_data):
                    row = i // 2
                    col = i % 2
                    x = start_x + col * (col_width + gap_between_cols)
                    y = start_y + row * row_height
                    
                    bg_rect = pygame.Rect(x, y, col_width, row_height - 10)
                    border_radius = 14
                    
                    draw_rounded_rect_alpha(surface, (0, 0, 0, 180), bg_rect, border_radius)
                    draw_rounded_rect_alpha(surface, (0, 0, 0, 0), bg_rect, border_radius,
                                           border_width=1, border_color_alpha=(60, 60, 80, 100))
                    
                    label_font_size = int(32 * self.scale)
                    if MONO_FONT_PATH:
                        label_font = pygame.font.Font(MONO_FONT_PATH, label_font_size)
                    else:
                        label_font = pygame.font.Font(None, label_font_size)
                    
                    label_text = get_prerendered_text(label_font, label + ":", GRAY)
                    
                    value_font_size = int(34 * self.scale)
                    if MONO_FONT_PATH:
                        value_font = pygame.font.Font(MONO_FONT_PATH, value_font_size)
                    else:
                        value_font = pygame.font.Font(None, value_font_size)
                    
                    value_text = get_prerendered_text(value_font, value, color)
                    
                    padding_x = 25
                    label_x = x + padding_x
                    label_y = y + (bg_rect.height - label_text.get_height()) // 2
                    
                    value_x = x + col_width - padding_x - value_text.get_width()
                    value_y = y + (bg_rect.height - value_text.get_height()) // 2
                    
                    surface.blit(label_text, (label_x, label_y))
                    surface.blit(value_text, (value_x, value_y))
        
        for i, option in enumerate(self.options):
            x, y, w, h = self.get_button_position(i)
            self.draw_button(surface, option["label"], x, y, w, h, i == self.hover_index)

# ============================================
# 🎮 Game Class
# ============================================

NOTE_COLORS = [
    (255, 50, 50), (255, 150, 0), (255, 255, 50), (50, 255, 50),
    (50, 200, 255), (50, 100, 255), (200, 50, 255), (255, 100, 200),
    (255, 200, 100), (100, 255, 200)
]

class Note:
    def __init__(self, lane, game_width, game_height, duration=0.3, track_labels=None, note_name="", actual_note="", speed_multiplier=1.0):
        self.lane = lane
        self.y = -30
        self.base_speed = 5.5 * (game_height / 720)
        self.speed = self.base_speed * speed_multiplier
        self.hit = False
        self.miss = False
        self.width = int(65 * (game_width / 1280))
        self.height = int(28 * (game_height / 720))
        self.duration = duration
        self.note_name = note_name
        self.actual_note = actual_note
        
        lane_spacing = game_width / 10
        self.x = (lane - 1) * lane_spacing + lane_spacing / 2 - self.width / 2
        
        self.color = NOTE_COLORS[lane - 1]
        self.glow = 0
        self.glow_direction = 1
        self.trail = []
        self.max_trail = 8
        self.pulse = 0
        
    def update(self):
        if not self.hit and not self.miss:
            self.y += self.speed
            self.glow += 0.05 * self.glow_direction
            if self.glow > 1 or self.glow < 0:
                self.glow_direction *= -1
            self.pulse = math.sin(time.time() * 4) * 0.3 + 0.7
            
            self.trail.append(self.y)
            if len(self.trail) > self.max_trail:
                self.trail.pop(0)
    
    def draw(self, surface):
        if self.hit or self.miss:
            return
        
        glow_size = int(15 * self.glow + 5)
        glow_rect = pygame.Rect(int(self.x) - glow_size, int(self.y) - glow_size,
                               self.width + glow_size*2, self.height + glow_size*2)
        
        glow_surface = pygame.Surface((glow_rect.width, glow_rect.height), pygame.SRCALPHA)
        color_with_alpha = (*self.color[:3], int(80 * self.pulse))
        pygame.draw.rect(glow_surface, color_with_alpha, glow_surface.get_rect(), border_radius=12)
        surface.blit(glow_surface, glow_rect)
        
        glow_size2 = int(8 * self.glow + 2)
        glow_rect2 = pygame.Rect(int(self.x) - glow_size2, int(self.y) - glow_size2,
                                self.width + glow_size2*2, self.height + glow_size2*2)
        glow_surface2 = pygame.Surface((glow_rect2.width, glow_rect2.height), pygame.SRCALPHA)
        color_with_alpha2 = (*self.color[:3], int(150 * self.pulse))
        pygame.draw.rect(glow_surface2, color_with_alpha2, glow_surface2.get_rect(), border_radius=10)
        surface.blit(glow_surface2, glow_rect2)
        
        rect = pygame.Rect(int(self.x), int(self.y), self.width, self.height)
        pygame.draw.rect(surface, self.color, rect, border_radius=6)
        
        for i in range(min(int(self.height // 2), 10)):
            brightness = 1.0 - (i / min(self.height // 2, 10)) * 0.4
            color = tuple(int(c * brightness) for c in self.color)
            y_pos = rect.y + i
            pygame.draw.line(surface, color, (rect.x + 4, y_pos), (rect.x + rect.width - 4, y_pos), 1)
        
        border_color = tuple(min(255, c + 100) for c in self.color[:3])
        pygame.draw.rect(surface, border_color, rect, border_radius=6, width=2)
        
        font_size = max(12, min(24, int(self.height * 0.6)))
        display_text = self.actual_note if self.actual_note else self.note_name
        
        if MONO_FONT_PATH:
            font = pygame.font.Font(MONO_FONT_PATH, font_size)
        else:
            font = pygame.font.Font(None, font_size)
            
        text = get_prerendered_text(font, display_text, WHITE)
        text_rect = text.get_rect(center=(self.x + self.width//2, self.y + self.height//2))
        surface.blit(text, text_rect)

class RhythmGame:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.notes = []
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.hit_count = 0
        self.miss_count = 0
        self.perfect_count = 0
        self.good_count = 0
        self.paused = False
        self.paused_by_hand = False
        self.hit_line = height - 90
        self.hit_zone_height = 35
        self.effects = []
        self.running = False
        self.is_demo = False
        self.demo_timer = 0
        self.frame_counter = 0
        self.showing_result = False
        
        self.prev_finger_states = {}
        self.lane_glow = [0] * 10
        self.lane_glow_decay = 0.92
        
        self.current_song = None
        self.current_key = 'C'
        self.song_notes = []
        self.song_index = 0
        self.song_timer = 0
        self.song_playing = False
        self.song_completed = False
        self.waiting_for_clear = False
        self.demo_finished = False
        self.scale_notes = {}
        self.speed_multiplier = 1.0
        
        # 等待计时器 - 用于延迟结算
        self.song_end_wait_timer = 0
        self.song_end_wait_duration = 90
        
        self.song_list = PianoSheet.get_song_list()
        self.current_song_index = 0
        
        self.particles = []
        self.max_particles = 30
        self.particle_spawn_rate = 2
        self.use_simple_particles = True
        
        self.particle_colors = {
            'perfect': (0, 255, 0),
            'great': (0, 255, 255),
            'good': (100, 100, 255),
            'miss': (255, 0, 0),
            'auto': (0, 255, 255)
        }
        
        self.particle_cache = {}
        self.track_labels = {}
        self.scale = min(width, height) / 720
        self.hit_zone_rect = pygame.Rect(0, self.hit_line, self.width, self.hit_zone_height)
        
        # 判定框缓存
        self.hitbox_cache = None
        self.hitbox_cache_key = None
        
        self.load_song(self.song_list[0]['id'])
    
    def load_song(self, song_name, speed_multiplier=1.0):
        song_data = PianoSheet.get_song(song_name)
        self.current_song = song_data['name']
        self.current_key = song_data.get('key', 'C')
        self.scale_notes = song_data['scale_notes']
        self.song_notes = song_data['notes']
        self.speed_multiplier = speed_multiplier
        self.song_index = 0
        self.song_timer = 0
        self.song_playing = True
        self.song_completed = False
        self.waiting_for_clear = False
        self.notes.clear()
        self.demo_finished = False
        self.showing_result = False
        self.song_end_wait_timer = 0
        
        self.track_labels = {}
        raw_labels = ['C4', 'D4', 'E4', 'F4', 'G4', 'A4', 'B4', 'C5', 'D5', 'E5']
        for i in range(10):
            self.track_labels[i+1] = raw_labels[i] if i < len(raw_labels) else f'Track {i+1}'
        
    def start(self, is_demo=False):
        self.running = True
        self.is_demo = is_demo
        self.song_completed = False
        self.waiting_for_clear = False
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.hit_count = 0
        self.miss_count = 0
        self.perfect_count = 0
        self.good_count = 0
        self.song_index = 0
        self.song_timer = 0
        self.song_playing = True
        self.notes.clear()
        self.particles.clear()
        self.effects.clear()
        self.paused = False
        self.paused_by_hand = False
        self.prev_finger_states = {}
        self.lane_glow = [0] * 10
        self.demo_timer = 0
        self.demo_finished = False
        self.frame_counter = 0
        self.showing_result = False
        self.song_end_wait_timer = 0
        
        # 清除判定框缓存
        self.hitbox_cache = None
        self.hitbox_cache_key = None
        
        audio_manager.stop_all()
    
    def stop(self):
        self.running = False
        self.is_demo = False
        audio_manager.stop_all()
    
    def toggle_pause(self, by_hand=False):
        self.paused = not self.paused
        if by_hand:
            self.paused_by_hand = self.paused
        if self.paused:
            audio_manager.stop_all()
    
    def resume(self):
        self.paused = False
        self.paused_by_hand = False
    
    def is_song_complete(self):
        if self.song_completed and len(self.notes) == 0:
            if self.song_end_wait_timer < self.song_end_wait_duration:
                self.song_end_wait_timer += 1
                return False
            return True
        return False
    
    def get_stats(self):
        total_notes = self.perfect_count + self.good_count + self.miss_count
        accuracy = 0
        if total_notes > 0:
            accuracy = (self.perfect_count + self.good_count) / total_notes * 100
        
        return {
            'score': self.score,
            'perfect': self.perfect_count,
            'good': self.good_count,
            'miss': self.miss_count,
            'max_combo': self.max_combo,
            'accuracy': accuracy
        }
    
    def set_showing_result(self, showing):
        self.showing_result = showing
    
    def spawn_song_note(self):
        if not self.song_playing or self.song_index >= len(self.song_notes):
            if self.song_index >= len(self.song_notes) and not self.song_completed:
                self.song_completed = True
                self.waiting_for_clear = True
                self.song_playing = False
            return
        
        note_name, duration = self.song_notes[self.song_index]
        actual_note = self.scale_notes.get(note_name, note_name)
        lane = random.randint(1, 10)
        
        if len(self.notes) < 30:
            note = Note(lane, self.width, self.height, duration, self.track_labels, note_name, actual_note, self.speed_multiplier)
            self.notes.append(note)
            self.song_index += 1
    
    def add_effect(self, x, y, text, color):
        self.effects.append({
            'x': x, 'y': y, 'text': text, 'color': color,
            'alpha': 255, 'life': 25
        })
        
        particle_count = min(5, self.max_particles // 6)
        for _ in range(particle_count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(1.5, 3.5)
            self.particles.append({
                'x': x, 'y': y,
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed - 1.5,
                'life': random.randint(10, 20),
                'max_life': 20,
                'color': color,
                'size': random.randint(1, 3)
            })
        
        if len(self.particles) > self.max_particles:
            self.particles = self.particles[-self.max_particles:]
    
    def update(self, active_fingers, hand_detected, finger_states=None):
        if not self.running:
            return
        
        self.frame_counter += 1
        
        if not self.is_demo and not hand_detected and not self.paused:
            self.toggle_pause(by_hand=True)
        
        if self.paused:
            return
        
        if self.is_demo:
            self.demo_timer += 1
            if self.song_playing and self.song_index < len(self.song_notes):
                if self.demo_timer >= 6:
                    self.spawn_song_note()
                    self.demo_timer = 0
            elif self.song_index >= len(self.song_notes) and not self.song_completed:
                self.song_completed = True
                self.waiting_for_clear = True
                self.song_playing = False
        else:
            pressed_fingers = []
            if finger_states is not None:
                for finger_name, is_extended in finger_states.items():
                    prev_state = self.prev_finger_states.get(finger_name, False)
                    if prev_state and not is_extended:
                        pressed_fingers.append(finger_name)
                self.prev_finger_states = finger_states.copy()
            
            pressed_numbers = []
            for finger_name in pressed_fingers:
                if finger_name in FINGER_MAP:
                    pressed_numbers.append(FINGER_MAP[finger_name])
            
            active_fingers = pressed_numbers
            
            if self.song_playing and self.song_index < len(self.song_notes):
                self.song_timer += 1
                
                if self.song_index < len(self.song_notes):
                    _, duration = self.song_notes[self.song_index]
                    spawn_delay = max(1, int(20 * duration / 0.2))
                else:
                    spawn_delay = 10
                
                if self.song_timer >= spawn_delay:
                    self.spawn_song_note()
                    self.song_timer = 0
            elif self.song_index >= len(self.song_notes) and not self.song_completed:
                self.song_completed = True
                self.waiting_for_clear = True
                self.song_playing = False
        
        for i in range(10):
            if (i + 1) in active_fingers:
                self.lane_glow[i] = 1.0
            else:
                self.lane_glow[i] *= self.lane_glow_decay
                if self.lane_glow[i] < 0.01:
                    self.lane_glow[i] = 0
        
        notes_to_remove = []
        hit_zone_top = self.hit_line
        hit_zone_bottom = self.hit_line + self.hit_zone_height
        hit_center = self.hit_line + self.hit_zone_height / 2
        
        PERFECT_THRESHOLD = 10
        GREAT_THRESHOLD = 22
        GOOD_THRESHOLD = 35
        
        for note in self.notes:
            note.update()
            
            if not note.hit and not note.miss:
                note_bottom = note.y + note.height
                
                if hit_zone_top <= note_bottom <= hit_zone_bottom:
                    if self.is_demo or note.lane in active_fingers:
                        center_y = note.y + note.height / 2
                        distance = abs(center_y - hit_center)
                        
                        if self.is_demo:
                            self.perfect_count += 1
                            self.add_effect(note.x + note.width/2, note.y, "AUTO", CYAN)
                            self.combo += 1
                            self.max_combo = max(self.max_combo, self.combo)
                            note.hit = True
                            sound = get_note_sound(note.actual_note, note.duration, play_immediately=True)
                            notes_to_remove.append(note)
                        elif distance < PERFECT_THRESHOLD:
                            self.score += 100 + self.combo * 5
                            self.perfect_count += 1
                            self.add_effect(note.x + note.width/2, note.y, "PERFECT!", GREEN)
                            self.combo += 1
                            self.hit_count += 1
                            self.max_combo = max(self.max_combo, self.combo)
                            note.hit = True
                            sound = get_note_sound(note.actual_note, note.duration, play_immediately=True)
                            notes_to_remove.append(note)
                        elif distance < GREAT_THRESHOLD:
                            self.score += 70 + self.combo * 3
                            self.good_count += 1
                            self.add_effect(note.x + note.width/2, note.y, "GREAT!", CYAN)
                            self.combo += 1
                            self.hit_count += 1
                            self.max_combo = max(self.max_combo, self.combo)
                            note.hit = True
                            sound = get_note_sound(note.actual_note, note.duration, play_immediately=True)
                            notes_to_remove.append(note)
                        elif distance < GOOD_THRESHOLD:
                            self.score += 50 + self.combo * 2
                            self.good_count += 1
                            self.add_effect(note.x + note.width/2, note.y, "GOOD", BLUE)
                            self.combo += 1
                            self.hit_count += 1
                            self.max_combo = max(self.max_combo, self.combo)
                            note.hit = True
                            sound = get_note_sound(note.actual_note, note.duration, play_immediately=True)
                            notes_to_remove.append(note)
                
                if note.y > self.height + 30:
                    if not self.is_demo:
                        note.miss = True
                        self.miss_count += 1
                        self.combo = 0
                        self.add_effect(note.x + note.width/2, self.hit_line, "MISS", RED)
                    notes_to_remove.append(note)
        
        for note in notes_to_remove:
            if note in self.notes:
                self.notes.remove(note)
        
        if self.particles:
            new_particles = []
            for particle in self.particles:
                particle['x'] += particle['vx']
                particle['y'] += particle['vy']
                particle['vy'] += 0.08
                particle['life'] -= 1
                if particle['life'] > 0:
                    new_particles.append(particle)
            self.particles = new_particles
        
        if self.effects:
            new_effects = []
            for effect in self.effects:
                effect['life'] -= 1
                effect['y'] -= 0.8
                effect['alpha'] = int(255 * (effect['life'] / 25))
                if effect['life'] > 0:
                    new_effects.append(effect)
            self.effects = new_effects
        
        if self.waiting_for_clear and len(self.notes) == 0:
            self.waiting_for_clear = False
            if self.is_demo:
                self.demo_finished = True
    
    def _get_hitbox_surface(self):
        """获取缓存的判定框表面 - 亮度调高"""
        cache_key = (self.width, self.height, self.hit_line, self.hit_zone_height, self.frame_counter // 30)
        
        if self.hitbox_cache is not None and self.hitbox_cache_key == cache_key:
            return self.hitbox_cache
        
        line_y = self.hit_line + self.hit_zone_height // 2
        box_width = self.width - 40
        box_height = self.hit_zone_height * 2
        box_x = 20
        box_y = line_y - box_height // 2
        radius = 8
        lane_spacing = self.width / 10
        
        box_surface = pygame.Surface((box_width, box_height), pygame.SRCALPHA)
        
        # 1. 背景 - 更亮
        for i in range(box_height):
            alpha = int(40 + 20 * (1 - abs(i - box_height/2) / (box_height/2)))
            color = (0, 120, 200, alpha)
            pygame.draw.line(box_surface, color, (0, i), (box_width, i))
        
        # 2. 边框 - 更亮更粗
        border_color = (0, 220, 255, 230)
        pygame.draw.rect(box_surface, border_color, (0, 0, box_width, box_height), border_radius=radius, width=3)
        
        # 边框发光 - 动态，更亮
        glow_alpha = int(80 + 50 * math.sin(self.frame_counter * 0.03))
        glow_color = (0, 220, 255, glow_alpha)
        pygame.draw.rect(box_surface, glow_color, (0, 0, box_width, box_height), border_radius=radius + 2, width=4)
        
        # 3. 中心线 - 更亮
        for i in range(3):
            alpha = 120 - i * 25
            pygame.draw.line(box_surface, (0, 220, 255, alpha), 
                           (30, box_height//2 + i), (box_width - 30, box_height//2 + i), 2)
        
        # 4. 四角光点 - 更亮更大
        corner_positions = [
            (10, 10), (box_width - 10, 10),
            (10, box_height - 10), (box_width - 10, box_height - 10)
        ]
        for cx, cy in corner_positions:
            pulse = 0.8 + 0.2 * math.sin(self.frame_counter * 0.04 + cx * 0.1)
            alpha = int(200 * pulse)
            pygame.draw.circle(box_surface, (0, 220, 255, alpha), (cx, cy), 4)
            pygame.draw.circle(box_surface, (0, 220, 255, int(alpha * 0.6)), (cx, cy), 8, 2)
        
        # 5. 车道分隔 - 更亮
        for i in range(1, 10):
            x = int(i * lane_spacing)
            if 0 < x < box_width:
                alpha = 60 + 30 * (1 - abs(x - box_width/2) / (box_width/2))
                pygame.draw.line(box_surface, (0, 220, 255, int(alpha)),
                               (x, 10), (x, box_height - 10), 2)
        
        self.hitbox_cache = box_surface
        self.hitbox_cache_key = cache_key
        
        return box_surface
    
    def draw(self, surface):
        game_bg = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        game_bg.fill((0, 0, 0, 40))
        surface.blit(game_bg, (0, 0))
        
        lane_spacing = self.width / 10
        
        for i in range(11):
            x = int(i * lane_spacing)
            color = (80, 80, 80) if i % 2 == 0 else (40, 40, 40)
            pygame.draw.line(surface, color, (x, 0), (x, self.height), 1)
        
        label_font_size = max(10, int(15 * self.scale))
        if MONO_FONT_PATH:
            font = pygame.font.Font(MONO_FONT_PATH, label_font_size)
        else:
            font = pygame.font.Font(None, label_font_size)
        
        for i in range(10):
            x = int(i * lane_spacing + lane_spacing / 2)
            label_bg_rect = pygame.Rect(int(x - lane_spacing/2 + 5), 5, int(lane_spacing - 10), 25)
            pygame.draw.rect(surface, (0, 0, 0, 150), label_bg_rect, border_radius=4)
            display_label = f"{i+1}"
            text = get_prerendered_text(font, display_label, GRAY)
            text_rect = text.get_rect(center=(x, 18))
            surface.blit(text, text_rect)
        
        for i in range(10):
            glow_intensity = self.lane_glow[i]
            if glow_intensity > 0.05:
                x = int(i * lane_spacing)
                alpha = int(60 * glow_intensity)
                if alpha > 5:
                    glow_rect = pygame.Rect(x, 0, int(lane_spacing), self.height)
                    glow_surface = pygame.Surface((int(lane_spacing), self.height), pygame.SRCALPHA)
                    glow_surface.fill((255, 255, 100, alpha))
                    surface.blit(glow_surface, (x, 0))
        
        hitbox_surface = self._get_hitbox_surface()
        line_y = self.hit_line + self.hit_zone_height // 2
        box_x = 20
        box_y = line_y - (self.hit_zone_height * 2) // 2
        surface.blit(hitbox_surface, (box_x, box_y))
        
        if self.particles:
            particles_by_color = {}
            for particle in self.particles:
                color_key = particle['color'][:3]
                if color_key not in particles_by_color:
                    particles_by_color[color_key] = []
                particles_by_color[color_key].append(particle)
            
            for color, particles in particles_by_color.items():
                for particle in particles:
                    alpha = int(255 * (particle['life'] / particle['max_life']))
                    if alpha > 10:
                        color_with_alpha = (*color, alpha)
                        pygame.draw.circle(
                            surface, 
                            color_with_alpha, 
                            (int(particle['x']), int(particle['y'])), 
                            particle['size']
                        )
        
        for note in self.notes:
            note.draw(surface)
        
        effect_font = pygame.font.Font(None, int(68 * self.scale))
        for effect in self.effects:
            text = get_prerendered_text(effect_font, effect['text'], effect['color'])
            text.set_alpha(effect['alpha'])
            text_rect = text.get_rect(center=(effect['x'], effect['y']))
            shadow = get_prerendered_text(effect_font, effect['text'], BLACK)
            shadow.set_alpha(int(effect['alpha'] * 0.5))
            shadow_rect = shadow.get_rect(center=(effect['x'] + 2, effect['y'] + 2))
            surface.blit(shadow, shadow_rect)
            surface.blit(text, text_rect)
        
        if self.song_completed and len(self.notes) == 0:
            wait_progress = self.song_end_wait_timer / self.song_end_wait_duration
            if wait_progress < 1.0:
                wait_font = pygame.font.Font(None, int(50 * self.scale))
                wait_text = get_prerendered_text(wait_font, "finalizing", CYAN)
                wait_rect = wait_text.get_rect(center=(self.width//2, self.height//2 + 80))
                
                alpha = int(128 + 127 * math.sin(self.frame_counter * 0.05))
                wait_text.set_alpha(alpha)
                surface.blit(wait_text, wait_rect)
                
                bar_width = 300
                bar_height = 6
                bar_x = self.width//2 - bar_width//2
                bar_y = self.height//2 + 130
                pygame.draw.rect(surface, (60, 60, 60), (bar_x, bar_y, bar_width, bar_height))
                pygame.draw.rect(surface, CYAN, (bar_x, bar_y, int(bar_width * wait_progress), bar_height))
        
        if self.running and not self.paused and not self.showing_result and self.combo > 1 and not self.is_demo:
            combo_font = pygame.font.Font(None, int(150 * self.scale))
            combo_text = get_prerendered_text(combo_font, str(self.combo), YELLOW)
            combo_shadow = get_prerendered_text(combo_font, str(self.combo), BLACK)
            combo_rect = combo_text.get_rect(center=(self.width//2, self.height//2 - 50))
            surface.blit(combo_shadow, (combo_rect.x + 3, combo_rect.y + 3))
            surface.blit(combo_text, combo_rect)
        
        if self.paused:
            s = pygame.Surface((self.width, self.height))
            s.set_alpha(180)
            s.fill(BLACK)
            surface.blit(s, (0, 0))
            pause_font = pygame.font.Font(None, int(110 * self.scale))
            pause_text = get_prerendered_text(pause_font, "PAUSED", YELLOW)
            pause_shadow = get_prerendered_text(pause_font, "PAUSED", BLACK)
            pause_rect = pause_text.get_rect(center=(self.width//2, self.height//2 - 80))
            surface.blit(pause_shadow, (pause_rect.x + 2, pause_rect.y + 2))
            surface.blit(pause_text, pause_rect)

# ============================================
# 🖱️ Cursor - 增大移动范围
# ============================================

class Cursor:
    def __init__(self):
        self.x = SCREEN_WIDTH // 2
        self.y = SCREEN_HEIGHT // 2
        self.radius = int(28 * font_scale)
        self.angle = 0
        self.is_fisting = False
        self.click_progress = 0
        self.is_clicked = False
        self.click_triggered = False
        self.reset_timer = 0
        self.click_hold_frames = 0
        self.CLICK_HOLD_THRESHOLD = 10
        self.visible = True
        self.click_available = False
        
        # 平滑插值
        self.smooth_x = SCREEN_WIDTH // 2
        self.smooth_y = SCREEN_HEIGHT // 2
        self.smooth_factor = 0.15
        
    def set_visible(self, visible):
        self.visible = visible
        
    def update(self, x, y, is_fisting):
        # 直接使用传入的坐标（已由主循环映射并放大）
        self.x = x
        self.y = y
        self.click_available = False
        
        if self.reset_timer > 0:
            self.reset_timer -= 1
            if self.reset_timer == 0:
                self.is_clicked = False
                self.click_triggered = False
                self.click_progress = 0
                self.click_hold_frames = 0
            return
        
        if is_fisting and not self.is_fisting:
            self.click_hold_frames = 0
            self.click_progress = 0
        elif not is_fisting and self.is_fisting:
            self.click_progress = 0
            self.click_hold_frames = 0
        
        self.is_fisting = is_fisting
        
        if is_fisting:
            if self.click_hold_frames < self.CLICK_HOLD_THRESHOLD:
                self.click_hold_frames += 1
                self.click_progress = self.click_hold_frames / self.CLICK_HOLD_THRESHOLD
            else:
                if not self.is_clicked:
                    self.is_clicked = True
                    self.click_triggered = False
                    self.click_progress = 1.0
                    self.click_available = True
                    self.reset_timer = 8
        else:
            if self.click_progress > 0:
                self.click_progress = max(0, self.click_progress - 0.03)
        
        self.angle += 0.05
        
    def is_click_active(self):
        if self.click_available and not self.click_triggered:
            return True
        return False
    
    def consume_click(self):
        if self.click_available and not self.click_triggered:
            self.click_triggered = True
            self.click_available = False
            return True
        return False
    
    def draw(self, surface):
        if not self.visible:
            return
            
        cx, cy = int(self.x), int(self.y)
        radius = self.radius
        
        if self.is_clicked:
            pulse = 3 + 2 * (self.reset_timer / 8)
            glow_radius = int(radius * 0.3 + pulse)
            
            for i in range(3):
                alpha = 30 - i * 10
                glow_surface = pygame.Surface((glow_radius*2 + 20, glow_radius*2 + 20), pygame.SRCALPHA)
                pygame.draw.circle(glow_surface, (*WHITE, alpha), (glow_radius + 10, glow_radius + 10), glow_radius + 10 - i*5)
                surface.blit(glow_surface, (cx - glow_radius - 10, cy - glow_radius - 10))
            
            fill_radius = int(radius * 0.7)
            pygame.draw.circle(surface, (*WHITE, 60), (cx, cy), fill_radius, 0)
            pygame.draw.circle(surface, WHITE, (cx, cy), 2)
        elif self.is_fisting or self.click_progress > 0.05:
            start_angle = -90
            points = []
            num_points = 60
            progress_radius = int(radius * 0.7)
            progress = min(1.0, self.click_progress)
            for i in range(num_points + 1):
                t = i / num_points
                angle_deg = start_angle + (360 * progress * t)
                angle_rad = np.radians(angle_deg)
                px = cx + progress_radius * np.cos(angle_rad)
                py = cy + progress_radius * np.sin(angle_rad)
                points.append((px, py))
            
            if len(points) > 1 and progress > 0.05:
                for i in range(len(points) - 1):
                    progress_i = i / len(points)
                    intensity = int(150 + 105 * progress_i)
                    color = (intensity, intensity, intensity)
                    pygame.draw.line(surface, color, points[i], points[i+1], 3)
            
            fill_radius = int(radius * 0.6 * progress)
            if fill_radius > 2:
                pygame.draw.circle(surface, (*WHITE, 30), (cx, cy), fill_radius, 0)
            pygame.draw.circle(surface, WHITE, (cx, cy), 2)
        else:
            pygame.draw.circle(surface, WHITE, (cx, cy), 2)
            
            num_dots = 8
            dot_radius_outer = int(radius * 0.7)
            for i in range(num_dots):
                angle_rad = np.radians(self.angle + i * (360 / num_dots))
                dot_x = cx + dot_radius_outer * np.cos(angle_rad)
                dot_y = cy + dot_radius_outer * np.sin(angle_rad)
                brightness = int(80 + 175 * (i / num_dots))
                pygame.draw.circle(surface, (brightness, brightness, brightness), (int(dot_x), int(dot_y)), 2)

# ============================================
# 📷 摄像头预览绘制函数
# ============================================

WRAP_CACHE = {}

def wrap_text(text, font, max_width):
    cache_key = (id(font), text, max_width)
    if cache_key in WRAP_CACHE:
        return WRAP_CACHE[cache_key].copy()
    
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        test_surface = font.render(test_line, True, WHITE)
        if test_surface.get_width() <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    
    if current_line:
        lines.append(' '.join(current_line))
    
    if len(WRAP_CACHE) > 30:
        WRAP_CACHE.clear()
    WRAP_CACHE[cache_key] = lines.copy()
    
    return lines

CAMERA_PREVIEW_CACHE = {}

def draw_camera_preview(surface, camera_frame_surface, camera_available, camera_initialized, 
                       hand_detected, hand_count, camera_fps, x, y, width, height):
    cam_bg = pygame.Rect(x - 8, y - 8, width + 16, height + 16)
    pygame.draw.rect(surface, (10, 10, 20, 200), cam_bg, border_radius=12)
    pygame.draw.rect(surface, (100, 100, 150, 255), cam_bg, border_radius=12, width=3)
    
    inner_bg = pygame.Rect(x - 4, y - 4, width + 8, height + 8)
    
    text_size = int(28 * font_scale)
    if text_size < 18:
        text_size = 18
    if text_size > 36:
        text_size = 36
        
    if MONO_FONT_PATH:
        text_font = pygame.font.Font(MONO_FONT_PATH, text_size)
    else:
        text_font = pygame.font.Font(None, text_size)
    
    if camera_frame_surface is not None and camera_available:
        pygame.draw.rect(surface, (30, 30, 50, 255), inner_bg, border_radius=8)
        surface.blit(camera_frame_surface, (x, y))
        
        if camera_fps > 0:
            fps_text = get_prerendered_text(text_font, f"{camera_fps} FPS", CYAN)
            fps_x = x + width - fps_text.get_width() - 15
            fps_y = y + 6
            surface.blit(fps_text, (fps_x, fps_y))
        
        if hand_detected:
            status_text = f"[H] {hand_count}" if hand_count >= 2 else f"[H] {hand_count}"
            color = GREEN if hand_count >= 2 else YELLOW
        else:
            status_text = "[N] 0"
            color = RED
        
        status_surface = get_prerendered_text(text_font, status_text, color)
        surface.blit(status_surface, (x + 10, y + 6))
    else:
        pygame.draw.rect(surface, BLACK, inner_bg, border_radius=8)
        
        status_text = "Camera initializing..." if not camera_initialized else "Camera unavailable"
        status_color = YELLOW if not camera_initialized else RED
        
        status_surface = get_prerendered_text(text_font, status_text, status_color)
        status_rect = status_surface.get_rect(center=(x + width // 2, y + height // 2))
        surface.blit(status_surface, status_rect)

# ============================================
# 🚀 Main Program
# ============================================

def main():
    print("=" * 60)
    print("Gesture Rhythm Master - Piano Mode (88-key Piano Samples)")
    print("=" * 60)
    print(f"Screen: {SCREEN_WIDTH}x{SCREEN_HEIGHT} (Fullscreen)")
    print(f"Sample Directory: {SAMPLES_DIR}")
    print(f"Audio Channels: {pygame.mixer.get_num_channels()}")
    print("Press ESC to exit, Q to quit")
    print("=" * 60)
    
    # 启动时预加载所有采样
    preload_all_samples()
    
    camera = CameraManager(fps=90)
    
    menu = Menu(SCREEN_WIDTH, SCREEN_HEIGHT, bg_images)
    game = RhythmGame(GAME_WIDTH, GAME_HEIGHT)
    result_screen = ResultScreen(SCREEN_WIDTH, SCREEN_HEIGHT, bg_images)
    cursor = Cursor()
    cursor.set_visible(True)
    
    clock = pygame.time.Clock()
    running = True
    in_game = False
    show_pause_menu = False
    showing_result = False
    result_shown = False
    
    mouse_x = SCREEN_WIDTH // 2
    mouse_y = SCREEN_HEIGHT // 2
    is_fisting = False
    fist_timer = 0
    FIST_THRESHOLD = 3
    
    # 增大光标移动范围 - 使用更大的缩放系数
    MOUSE_SCALE = 5.0
    
    TARGET_FPS = 60
    
    pygame.event.set_allowed([pygame.QUIT, pygame.KEYDOWN])
    
    frame_count = 0
    fps_timer = time.time()
    current_fps = 0
    
    try:
        while running:
            frame_start = time.time()
            
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if showing_result:
                            showing_result = False
                            result_shown = False
                            result_screen.hide()
                            game.set_showing_result(False)
                            in_game = False
                            game.stop()
                            menu.set_visible(True)
                            menu.show_main()
                            cursor.set_visible(True)
                        elif in_game:
                            if game.paused:
                                in_game = False
                                show_pause_menu = False
                                game.stop()
                                menu.set_visible(True)
                                menu.set_pause_menu(False)
                                menu.show_main()
                                cursor.set_visible(True)
                            else:
                                game.toggle_pause()
                                show_pause_menu = True
                                menu.set_visible(True)
                                menu.set_pause_menu(True)
                                cursor.set_visible(True)
                        else:
                            running = False
                    elif event.key == pygame.K_q:
                        running = False
                    elif event.key == pygame.K_SPACE and in_game and not showing_result:
                        if not game.paused:
                            game.toggle_pause()
                            show_pause_menu = True
                            menu.set_visible(True)
                            menu.set_pause_menu(True)
                            cursor.set_visible(True)
                        elif not show_pause_menu:
                            game.resume()
                            show_pause_menu = False
                            menu.set_visible(False)
                            cursor.set_visible(False)
            
            frame = camera.get_frame()
            camera_available = camera.is_available()
            camera_initialized = camera.is_initialized()
            hand_detected = False
            camera_frame_surface = None
            camera_fps = 0
            hand_count = 0
            active_numbers = []
            all_finger_states = {}
            
            if frame is not None and camera_available:
                frame = cv2.flip(frame, 1)
                camera_fps = camera.get_fps()
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = hands.process(rgb_frame)
                
                if results.multi_hand_landmarks:
                    hand_detected = True
                    hand_count = len(results.multi_hand_landmarks)
                    
                    for idx, (hand_landmarks, handedness) in enumerate(
                            zip(results.multi_hand_landmarks, results.multi_handedness)):
                        is_left = handedness.classification[0].label == 'Left'
                        finger_states = get_finger_states(hand_landmarks, is_left)
                        all_finger_states.update(finger_states)
                        
                        if idx == 0:
                            hx, hy = get_hand_center(hand_landmarks)
                            # 使用更大的缩放系数映射到全屏
                            # 将手部坐标从[0,1]映射到[-1,1]，然后缩放
                            center_x = 0.5
                            center_y = 0.5
                            offset_x = (hx - center_x) * 2  # [-1, 1]
                            offset_y = (hy - center_y) * 2  # [-1, 1]
                            
                            # 应用缩放
                            screen_x = SCREEN_WIDTH // 2 + offset_x * SCREEN_WIDTH * MOUSE_SCALE / 2
                            screen_y = SCREEN_HEIGHT // 2 + offset_y * SCREEN_HEIGHT * MOUSE_SCALE / 2
                            
                            # 边界限制
                            margin = cursor.radius + 5
                            screen_x = max(margin, min(SCREEN_WIDTH - margin, screen_x))
                            screen_y = max(margin, min(SCREEN_HEIGHT - margin, screen_y))
                            
                            # 平滑插值
                            mouse_x = mouse_x * (1 - 0.2) + screen_x * 0.2
                            mouse_y = mouse_y * (1 - 0.2) + screen_y * 0.2
                            
                            if is_fist(finger_states, is_left):
                                fist_timer += 1
                                if fist_timer >= FIST_THRESHOLD:
                                    is_fisting = True
                            else:
                                fist_timer = 0
                                is_fisting = False
                        
                        mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS,
                                                 mp_drawing_styles.get_default_hand_landmarks_style(),
                                                 mp_drawing_styles.get_default_hand_connections_style())
                else:
                    fist_timer = 0
                    is_fisting = False
                
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_resized = cv2.resize(frame_rgb, (CAMERA_PREVIEW_WIDTH, CAMERA_PREVIEW_HEIGHT))
                frame_surface = pygame.surfarray.make_surface(frame_resized.swapaxes(0, 1))
                camera_frame_surface = frame_surface
            
            cursor.update(mouse_x, mouse_y, is_fisting)
            click_active = cursor.is_click_active()
            
            if in_game and not showing_result and not result_shown and game.is_song_complete():
                showing_result = True
                result_shown = True
                game.set_showing_result(True)
                stats = game.get_stats()
                result_screen.show(stats, is_demo=game.is_demo)
                game.stop()
                cursor.set_visible(True)
            
            screen.fill(BLACK)
            
            sidebar_rect = pygame.Rect(GAME_WIDTH, 0, SIDEBAR_WIDTH, SCREEN_HEIGHT)
            pygame.draw.rect(screen, (20, 20, 35, 220), sidebar_rect)
            pygame.draw.line(screen, (100, 100, 150), (GAME_WIDTH, 0), (GAME_WIDTH, SCREEN_HEIGHT), 3)
            
            if in_game and not showing_result:
                game.update(active_numbers, hand_detected, all_finger_states)
                
                if game.paused and not show_pause_menu and game.paused_by_hand:
                    show_pause_menu = True
                    menu.set_visible(True)
                    menu.set_pause_menu(True)
                    cursor.set_visible(True)
                
                game_surface = pygame.Surface((GAME_WIDTH, GAME_HEIGHT))
                game.draw(game_surface)
                screen.blit(game_surface, (0, 0))
                
                sidebar_y = 15
                
                title = get_prerendered_text(FONT_MONO_MEDIUM, "Game Info", WHITE)
                title_bg_rect = pygame.Rect(GAME_WIDTH + SIDEBAR_WIDTH//2 - title.get_width()//2 - 15,
                                           sidebar_y + 30 - title.get_height()//2 - 5,
                                           title.get_width() + 30, title.get_height() + 10)
                pygame.draw.rect(screen, (0, 0, 0, 150), title_bg_rect, border_radius=8)
                title_rect = title.get_rect(center=(GAME_WIDTH + SIDEBAR_WIDTH//2, sidebar_y + 30))
                screen.blit(title, title_rect)
                sidebar_y += 65
                
                song_name = game.current_song
                song_lines = wrap_text(song_name, FONT_MONO_SMALL, SIDEBAR_WIDTH - 30)
                for line in song_lines:
                    song_text = get_prerendered_text(FONT_MONO_SMALL, line, YELLOW)
                    song_rect = song_text.get_rect(center=(GAME_WIDTH + SIDEBAR_WIDTH//2, sidebar_y + 20))
                    screen.blit(song_text, song_rect)
                    sidebar_y += 40
                sidebar_y += 5
                
                diff_text = f"Speed: {game.speed_multiplier:.1f}x"
                diff_surface = get_prerendered_text(FONT_MONO_SMALL, diff_text, CYAN)
                diff_rect = diff_surface.get_rect(center=(GAME_WIDTH + SIDEBAR_WIDTH//2, sidebar_y + 20))
                screen.blit(diff_surface, diff_rect)
                sidebar_y += 40
                
                pygame.draw.line(screen, (60, 60, 80), (GAME_WIDTH + 15, sidebar_y), (GAME_WIDTH + SIDEBAR_WIDTH - 15, sidebar_y), 1)
                sidebar_y += 20
                
                score_title = get_prerendered_text(FONT_MONO_SMALL, "Score", WHITE)
                score_title_rect = score_title.get_rect(center=(GAME_WIDTH + SIDEBAR_WIDTH//2, sidebar_y + 18))
                screen.blit(score_title, score_title_rect)
                sidebar_y += 40
                
                if game.is_demo:
                    demo_text = get_prerendered_text(FONT_MONO_MEDIUM, "DEMO MODE", CYAN)
                    demo_rect = demo_text.get_rect(center=(GAME_WIDTH + SIDEBAR_WIDTH//2, sidebar_y + 22))
                    screen.blit(demo_text, demo_rect)
                    sidebar_y += 50
                else:
                    score_text = get_prerendered_text(FONT_MONO_LARGE, str(game.score), GOLD)
                    score_rect = score_text.get_rect(center=(GAME_WIDTH + SIDEBAR_WIDTH//2, sidebar_y + 30))
                    screen.blit(score_text, score_rect)
                    sidebar_y += 65
                    
                    stats_title = get_prerendered_text(FONT_MONO_SMALL, "Statistics", WHITE)
                    stats_title_rect = stats_title.get_rect(center=(GAME_WIDTH + SIDEBAR_WIDTH//2, sidebar_y + 15))
                    screen.blit(stats_title, stats_title_rect)
                    sidebar_y += 35
                    
                    stats = [
                        (f"Perfect: {game.perfect_count}", GREEN),
                        (f"Good: {game.good_count}", CYAN),
                        (f"Miss: {game.miss_count}", RED),
                        (f"Combo: {game.combo}", YELLOW),
                        (f"Max Combo: {game.max_combo}", GOLD)
                    ]
                    
                    for text, color in stats:
                        stat_text = get_prerendered_text(FONT_MONO_TINY, text, color)
                        stat_rect = stat_text.get_rect(center=(GAME_WIDTH + SIDEBAR_WIDTH//2, sidebar_y + 14))
                        screen.blit(stat_text, stat_rect)
                        sidebar_y += 30
                
                if show_pause_menu:
                    result = menu.update(mouse_x, mouse_y, click_active)
                    if result:
                        if result["action"] == "resume":
                            game.resume()
                            show_pause_menu = False
                            menu.set_visible(False)
                            cursor.set_visible(False)
                            cursor.consume_click()
                        elif result["action"] == "quit_menu":
                            in_game = False
                            show_pause_menu = False
                            result_shown = False
                            game.stop()
                            menu.set_visible(True)
                            menu.set_pause_menu(False)
                            menu.show_main()
                            cursor.set_visible(True)
                            cursor.consume_click()
                    
                    menu.draw(screen)
                    cursor.draw(screen)
                else:
                    cursor.set_visible(False)
            
            elif showing_result:
                result_screen.draw(screen)
                cursor.set_visible(True)
                cursor.draw(screen)
                
                result = result_screen.update(mouse_x, mouse_y, click_active)
                if result:
                    if result["action"] == "retry":
                        cursor.consume_click()
                        showing_result = False
                        result_shown = False
                        result_screen.hide()
                        game.set_showing_result(False)
                        song_id = None
                        for s in game.song_list:
                            if s['name'] == game.current_song:
                                song_id = s['id']
                                break
                        if not song_id:
                            song_id = 'twinkle'
                        game.load_song(song_id, game.speed_multiplier)
                        game.start(is_demo=False)
                        cursor.set_visible(False)
                    elif result["action"] == "menu":
                        cursor.consume_click()
                        showing_result = False
                        result_shown = False
                        result_screen.hide()
                        game.set_showing_result(False)
                        in_game = False
                        game.stop()
                        menu.set_visible(True)
                        menu.show_main()
                        cursor.set_visible(True)
            
            else:
                result = menu.update(mouse_x, mouse_y, click_active)
                if result:
                    action = result["action"]
                    if action == "start_game":
                        cursor.consume_click()
                        game.load_song(result["song"], result["speed"])
                        game.start(is_demo=False)
                        in_game = True
                        result_shown = False
                        menu.set_visible(False)
                        cursor.set_visible(False)
                    elif action == "demo":
                        cursor.consume_click()
                        game.load_song(result["song"], result["speed"])
                        game.start(is_demo=True)
                        in_game = True
                        result_shown = False
                        menu.set_visible(False)
                        cursor.set_visible(False)
                    elif action == "quit":
                        running = False
                
                menu.draw(screen)
                cursor.set_visible(True)
                cursor.draw(screen)
            
            cam_y = SCREEN_HEIGHT - CAMERA_PREVIEW_HEIGHT - 10
            draw_camera_preview(screen, camera_frame_surface, camera_available, camera_initialized,
                               hand_detected, hand_count, camera_fps,
                               CAMERA_PREVIEW_X, cam_y, CAMERA_PREVIEW_WIDTH, CAMERA_PREVIEW_HEIGHT)
            
            pygame.display.flip()
            
            frame_end = time.time()
            frame_duration = frame_end - frame_start
            sleep_time = max(0, 1.0 / TARGET_FPS - frame_duration)
            if sleep_time > 0:
                time.sleep(sleep_time)
            
            frame_count += 1
            if time.time() - fps_timer >= 1.0:
                current_fps = frame_count
                frame_count = 0
                fps_timer = time.time()
            
            clock.tick(TARGET_FPS + 10)
    
    except KeyboardInterrupt:
        print("User interrupted")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        audio_manager.stop_all()
        camera.stop()
        pygame.quit()

if __name__ == "__main__":
    main()
