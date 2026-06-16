"""
RockTranslate — Core Configuration and Constant Definitions
Path: src/rocktranslate/core/constants.py

This module consolidates all static properties, API endpoints, model rules, 
network retry budgets, physical PDF layout constants, and interface configurations.
Centralizing these elements ensures clean modular boundaries and eases open-source maintenance.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os, sys
from typing import Final, Dict, Set, List, Tuple

# ==============================================================================
# 1. FILE SYSTEM AND ASSETS PATHS
# ==============================================================================

# Dynamic path resolution to src/assets to guarantee cross-platform consistency.
# DEFAULT_ASSETS_DIR: Final[str] = os.path.abspath(
#     os.path.join(os.path.dirname(__file__), "..", "assets")
# )


# Dynamic path resolution supporting both local source development and
# compiled standalone PyInstaller extraction directories (_MEIPASS).
if hasattr(sys, "_MEIPASS"):
    # Target path inside PyInstaller standard extraction directory
    DEFAULT_ASSETS_DIR: Final[str] = os.path.abspath(
        os.path.join(sys._MEIPASS, "rocktranslate", "assets")
    )
else:
    # Target path in local active development mode: core/../assets -> rocktranslate/assets
    DEFAULT_ASSETS_DIR: Final[str] = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "assets")
    )


# Remote URLs for automatic dependency downloads
PDFJS_DOWNLOAD_URL: Final[str] = (
    "https://github.com/mozilla/pdf.js/releases/download/v3.11.174/pdfjs-3.11.174-dist.zip"
)

PDF2HTMLEX_DOWNLOAD_URL: Final[str] = (
    "https://shuvomoy.github.io/blogs/assets/pdf2htmlEX/pdf2htmlEX-win32-0.14.6-with-poppler-data.zip"
)


# ==============================================================================
# 2. AI MODEL CONFIGURATIONS & TOKEN BOUNDARIES
# ==============================================================================

# Default model routing used when initiating clients without custom user preferences
DEFAULT_MODEL: Final[str] = "gemini/gemini-3.1-flash-lite"
DEFAULT_TOKEN_LIMIT: Final[int] = 1000

# Limits on usable context tokens for input segments, preventing prompt truncation
MODEL_TOKEN_LIMITS: Final[Dict[str, int]] = {
    # Lightweight Models (optimized for high-frequency low-latency batches)
    "gemini/gemini-3.5-flash": 1500,
    "gemini/gemini-3.1-flash-lite": 1000,
    "gemini/gemini-2.5-flash-lite": 1000,
    "gemini/gemini-3-flash-preview": 1000,
    "gemini/gemini-2.5-flash": 1500,
    "gemini/gemini-2.0-flash": 1500,
    "gemini/gemini-2.0-flash-lite": 1000,
    "gpt-4o-mini": 1500,
    "gpt-5-mini": 1500,
    "gpt-5-nano": 1000,
    "ollama/mistral": 800,
    "ollama/llama3": 800,
    
    # Large Reasoning Models (pro-tier and advanced research targets)
    "gemini/gemini-3.1-pro": 2500,
    "gemini/gemini-2.5-pro": 2500,
    "gemini/gemini-1.5-pro": 2500,
    "gpt-4o": 2500,
    "gpt-5": 2500,
    "gpt-5.5": 2500,
    "claude-3-5-sonnet-20241022": 2500,
    "claude-4-sonnet": 2500,
    "claude-4.6-sonnet": 2500,
    "claude-sonnet-4-20250514": 2500,
}

# Supported AI providers, dynamic prefixes, env keys, and suggested models
DEFAULT_PROVIDERS: Final[Dict[str, Dict[str, object]]] = {
    "Google Gemini": {
        "prefix": "gemini/",
        "key_env": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/",
        "models": [
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-pro",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-exp-1206"
        ]
    },

    "OpenAI": {
        "prefix": "openai/",
        "key_env": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "models": [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-5.5",
            "gpt-5.4",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
            "chatgpt-4o-latest",
            "o1",
            "o1-mini",
            "o1-preview",
            "o3",
            "o3-mini",
            "o4-mini"
        ]
    },

    "Anthropic": {
        "prefix": "anthropic/",
        "key_env": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": [
            "claude-4.8-opus",           
            "claude-4.6-sonnet",         
            "claude-4.5-haiku",
            "claude-4-opus",
            "claude-4-sonnet",
            "claude-3-7-sonnet",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]
    },

    "DeepSeek": {
        "prefix": "deepseek/",
        "key_env": "DEEPSEEK_API_KEY",
        "key_url": "https://platform.deepseek.com/api_keys",
        "models": [
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-v3",
            "deepseek-r1"
        ]
    },

    "Mistral AI": {
        "prefix": "mistral/",
        "key_env": "MISTRAL_API_KEY",
        "key_url": "https://console.mistral.ai/api-keys/",
        "models": [
            "mistral-medium-3.5",
            "mistral-small-latest",
            "mistral-large-latest",
            "mistral-medium-latest",
            "mistral-small-latest",
            "pixtral-large-latest",
            "pixtral-12b",
            "ministral-8b-latest",
            "ministral-3b-latest",
            "open-mistral-nemo",
            "open-mixtral-8x22b",
            "open-mixtral-8x7b"
        ]
    },

    "Groq": {
        "prefix": "groq/",
        "key_env": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        "models": [
            "llama-4-scout-groq",        
            "llama-3.3-70b-versatile",   
            "llama3-70b-8192",
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
            "qwen-qwq-32b",
            "deepseek-r1-distill-llama-70b"
        ]
    },

    "Together AI": {
        "prefix": "together_ai/",
        "key_env": "TOGETHERAI_API_KEY",
        "key_url": "https://api.together.xyz/settings/api-keys",
        "models": [
            "meta-llama/Llama-4-Maverick",         
            "meta-llama/Llama-4-Scout",            
            "meta-llama/Meta-Llama-3.1-405B-Instruct",
            "meta-llama/Meta-Llama-3.3-70B-Instruct",
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "meta-llama/Llama-3.1-405B-Instruct-Turbo",
            "meta-llama/Llama-3.1-70B-Instruct-Turbo",
            "meta-llama/Llama-3.1-8B-Instruct-Turbo",
            "Qwen/Qwen3-235B-A22B",
            "Qwen/Qwen3-32B",
            "Qwen/Qwen2.5-72B-Instruct",
            "deepseek-ai/DeepSeek-V4-Pro",
            "deepseek-ai/DeepSeek-R1",
            "deepseek-ai/DeepSeek-V3",
            "mistralai/Mixtral-8x7B-Instruct-v0.1",
            "mistralai/Mixtral-8x22B-Instruct-v0.1",
            "moonshotai/Kimi-K2",
            "zai-org/GLM-4.7"
        ]
    },

    "Moonshot (Kimi)": {
        "prefix": "moonshot/",
        "key_env": "MOONSHOT_API_KEY",
        "key_url": "https://platform.moonshot.cn/console/api-keys",
        "models": [
            "kimi-k2.6",                 
            "kimi-k2.5",              
            "kimi-k2",
            "kimi-k2-instruct",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k"
        ]
    },

    "Alibaba DashScope (Qwen)": {
        "prefix": "dashscope/",
        "key_env": "DASHSCOPE_API_KEY",
        "key_url": "https://bailian.console.aliyun.com/?tab=model#/api-key",
        "models": [
            "qwen3.7-max-preview",       
            "qwen3.5-plus",                  
            "qwen-max",                  
            "qwen-plus",
            "qwen-turbo",
            "qwen-long",
            "qwen2.5-72b-instruct",
            "qwen2.5-32b-instruct",
            "qwen2.5-14b-instruct",
            "qwen2.5-7b-instruct",
            "qwen3-235b-a22b",
            "qwen3-32b",
            "qwq-32b"
        ]
    },

    "Zhipu AI (GLM)": {
        "prefix": "zai/",
        "key_env": "ZAI_API_KEY",
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "models": [
            "glm-5.1",                   
            "glm-5",                   
            "glm-4.7",
            "glm-4.6",
            "glm-4.5",
            "glm-4-air",
            "glm-4-airx",
            "glm-4-plus",
            "glm-4-long"
        ]
    },

    "xAI (Grok)": {
        "prefix": "xai/",
        "key_env": "XAI_API_KEY",
        "key_url": "https://console.x.ai/",
        "models": [
            "grok-4",
            "grok-3",
            "grok-3-mini",
            "grok-2-1212",
            "grok-beta"
        ]
    },

    "OpenRouter": {
        "prefix": "openrouter/",
        "key_env": "OPENROUTER_API_KEY",
        "key_url": "https://openrouter.ai/keys",
        "models": [
            "openrouter/free", 
            "google/gemini-2.5-flash:free", 
            "meta-llama/llama-3-8b-instruct:free", 
            "nex-agi/nex-n2-pro:free",
            "nvidia/nemotron-3.5-content-safety:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "poolside/laguna-m1:free",
            "nvidia/nemotron-3-super:free",
            "openai/gpt-oss-120b:free",
            "google/gemma-4-31b:free",
            "nvidia/nemotron-3-nano-30b-a3b:free",
            "nvidia/nemotron-3-nano-omni:free",
            "nvidia/nemotron-nano-12b-vl:free",
            "inclusionai/ring-2.6-1t:free",
            "baidu/cobuddy:free",
            "openai/gpt-5",
            "openai/gpt-5-mini",
            "openai/gpt-4.1",
            "openai/gpt-4o",

            "nvidia/nemotron-3-ultra-550b-a55b",
            "minimax/minimax-m3",
            "stepfun/step-3.7-flash",
            "inclusionai/ring-2.6-1t",
            "ibm-granite/granite-4.1-8b",
            "poolside/laguna-xs.2:free",
            
            "anthropic/claude-opus-4.8-fast",
            "anthropic/claude-opus-4.7-fast",
            "anthropic/claude-4-opus",
            "anthropic/claude-4-sonnet",
            "anthropic/claude-4.6-sonnet",
            "anthropic/claude-4.8-opus",
            "anthropic/claude-4.5-haiku",
            "anthropic/claude-3.7-sonnet",
            
            "google/gemini-2.5-pro",
            "google/gemini-2.5-flash",
            "google/gemini-3.5-flash",
            "google/gemini-3.1-flash-lite",

            "openai/gpt-chat-latest",
            "~openai/gpt-mini-latest",

            "deepseek/deepseek-r1",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-v3",
            "deepseek/deepseek-v4-flash",
            "deepseek/deepseek-v4-pro",
            
            "x-ai/grok-4.3",
            "x-ai/grok-4",
            "x-ai/grok-3",
             
            "qwen/qwen3.5-plus-20260420",
            "qwen/qwen3.6-35b-a3b",
            "qwen/qwen3.7-max",
            "qwen/qwen3-235b-a22b",
            "qwen/qwen2.5-72b-instruct",
            "qwen/qwen-3.5-397b-instruct",

            "meta-llama/llama-3.3-70b-instruct",
            "meta-llama/llama-3.1-405b-instruct",
             
            "mistralai/mistral-large",
            "mistralai/mistral-medium-3.5", 
            "moonshotai/kimi-k2",
            "z-ai/glm-4.7"
        ]
    }
}


# ==============================================================================
# 3. TRANSLATION SLICING & NETWORK RETRIES
# ==============================================================================

# Safeguard limits on structural translation chunks and API retries
MAX_SEGMENTS_PER_BATCH: Final[int] = 60
SLIDING_CONTEXT_MAX_SIZE: Final[int] = 5

MAX_RETRIES: Final[int] = 4
RETRY_DELAYS: Final[List[float]] = [2.0, 3.0, 6.0]


# ==============================================================================
# 4. GEOFITTING & PDF PARSING THRESHOLDS
# ==============================================================================

# Margin in horizontal pixels where spacers trigger a structural table separation
THRESHOLD_PX: Final[float] = 12.0

# Legacy typographic accent splinters to skip during reconstruction
ACCENTS_TO_IGNORE: Final[Set[str]] = {
    '´', '`', '¨', 'ˆ', '˜', '¸', 'ˇ', '¯', '˘', '˙', '˚', '˝', '˛', '⇑', '⇓'
}


# ==============================================================================
# 5. TRANSLATION LANGUAGE REGISTRY
# ==============================================================================

SUPPORTED_LANGUAGES: Final[Dict[str, str]] = {
    "fr": "French",
    "en": "English",
    "es": "Spanish",
    "de": "German",
    "zh": "Chinese (Simplified)",
    "ar": "Arabic",
    "pt": "Portuguese",
    "it": "Italian",
    "ja": "Japanese",
    "ru": "Russian",
}

DEFAULT_LANG_CODE: Final[str] = "fr"
DEFAULT_LANG_NAME: Final[str] = SUPPORTED_LANGUAGES[DEFAULT_LANG_CODE]