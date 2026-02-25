import json
import os
import requests
import subprocess
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

# Configuration for local storage
BASE_DIR = os.path.dirname(__file__)
LOGOS_METADATA = os.path.join(BASE_DIR, "company_logos.json")
STATIC_LOGOS_DIR = os.path.join(BASE_DIR, "static", "logos")

# Ensure static directory exists
os.makedirs(STATIC_LOGOS_DIR, exist_ok=True)

def _load_metadata():
    if os.path.exists(LOGOS_METADATA):
        try:
            with open(LOGOS_METADATA, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_metadata(metadata):
    with open(LOGOS_METADATA, "w") as f:
        json.dump(metadata, f, indent=2)

def _get_favicon_url(domain):
    return f"https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=http://{domain}&size=128"

def _search_domain_with_ai(company_name):
    """Use AI (Claude CLI) to find the official website domain of a company."""
    prompt = f"Find the official website domain for the AI company '{company_name}'. Return ONLY the domain name (e.g. anthropic.com). If unknown, return 'unknown'."
    try:
        # Using claude-cli as requested
        result = subprocess.check_output(["claude", "-p", prompt], stderr=subprocess.STDOUT, text=True).strip()
        domain = result.lower().replace("http://", "").replace("https://", "").split("/")[0]
        if "." in domain and domain != "unknown":
            return domain
    except Exception as e:
        print(f"AI search failed for {company_name}: {e}")
    return None

def _search_domain_fallback(company_name):
    """Fallback to DDG search for domain."""
    overrides = {
        "Google": "google.com",
        "Meta": "meta.com",
        "OpenAI": "openai.com",
        "Anthropic": "anthropic.com",
        "Microsoft": "microsoft.com",
        "Mistral": "mistral.ai",
        "xAI": "x.ai",
        "DeepSeek": "deepseek.com",
        "Alibaba": "alibaba.com",
        "Cohere": "cohere.com",
        "NVIDIA": "nvidia.com",
        "Moonshot": "moonshot.cn",
        "Zhipu": "zhipuai.cn",
        "IBM": "ibm.com",
        "AI2": "allenai.org",
        "AI21 Labs": "ai21.com",
        "01.AI": "01.ai",
        "ByteDance": "seed.bytedance.com",
        "MiniMax": "minimax.io",
        "Baidu": "baidu.com",
    }
    if company_name in overrides:
        return overrides[company_name]

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.post('https://html.duckduckgo.com/html/', data={'q': f'{company_name} AI company official website'}, headers=headers, timeout=5)
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = soup.select('a.result__url')
        if links:
            url = links[0].get('href', '')
            parsed = urlparse(url)
            if 'uddg=' in parsed.query:
                qs = parse_qs(parsed.query)
                if 'uddg' in qs:
                    url = qs['uddg'][0]
                    parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split('/')[0]
            if domain: return domain
    except Exception:
        pass
    return f"{company_name.lower().replace(' ', '')}.com"

def _download_logo(company_name, domain):
    """Download logo from Google Favicon service and save locally."""
    url = _get_favicon_url(domain)
    filename = f"{company_name.lower().replace(' ', '_').replace('.', '_')}.png"
    local_path = os.path.join(STATIC_LOGOS_DIR, filename)
    
    try:
        resp = requests.get(url, stream=True, timeout=10)
        if resp.status_code == 200:
            with open(local_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return f"/static/logos/{filename}"
    except Exception as e:
        print(f"Failed to download logo for {company_name}: {e}")
    return None

def get_logo(company_name):
    if not company_name or company_name == "Unknown":
        return None
        
    metadata = _load_metadata()
    if company_name in metadata:
        return metadata[company_name]
        
    # Phase 1: Try AI to get domain
    domain = _search_domain_with_ai(company_name)
    
    # Phase 2: Fallback to manual/DDG
    if not domain:
        domain = _search_domain_fallback(company_name)
    
    # Phase 3: Download and save locally
    local_url = _download_logo(company_name, domain)
    
    if local_url:
        metadata[company_name] = local_url
        _save_metadata(metadata)
        return local_url
    
    return None
