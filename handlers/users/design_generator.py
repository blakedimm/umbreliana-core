# File: handlers/syndicate/design_generator.py
import os
from html2image import Html2Image

# ==========================================
# 🚀 ОПТИМИЗАЦИЯ РЕНДЕРА (АГРЕССИВНЫЕ ФЛАГИ)
# ==========================================
fast_chrome_flags = [
    '--no-sandbox', 
    '--disable-gpu', 
    '--hide-scrollbars',
    '--disable-dev-shm-usage',
    '--disable-extensions',
    '--disable-background-networking',
    '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--disable-software-rasterizer',
    '--mute-audio',
    '--no-first-run',
    '--no-default-browser-check',
    '--no-zygote'
]

hti = Html2Image(custom_flags=fast_chrome_flags)

def fmt(x):
    return f"{int(x):,}".replace(',', ' ')

# ==========================================
# 🎨 СЛОВАРЬ ДЕФОЛТОВ (ДЛЯ РУССКОГО ФОЛБЕКА)
# ==========================================
FALLBACK_STRINGS = {
    "img_reg_agent": "ЗАРЕГИСТРИРОВАННЫЙ АГЕНТ",
    "img_db_empty": "<i>[ БАЗА ДАННЫХ ПУСТА ]</i>",
    "img_lbl_credits": "Доступные Кредиты",
    "img_lbl_crypto": "Крипто-Кошелек",
    "img_lbl_gold": "Золотой Запас",
    "img_lbl_alias": "Псевдоним Агента",
    "img_lbl_net_status": "Статус в Сети",
    "img_lbl_standing": "Социальный Status",
    "img_lbl_affiliation": "Принадлежность",
    "img_lbl_clearances": "ПРОВЕРЕННЫЕ ДОСТУПЫ БЕЗОПАСНОСТИ",
    "img_farm_title": "ТЕРМИНАЛ УПРАВЛЕНИЯ ФЕРМОЙ",
    "img_lbl_hashrate": "ТЕКУЩАЯ СКОРОСТЬ ХЭШРЕЙТА",
    "img_title_finances": "ФИНАНСЫ",
    "img_lbl_collected": "Собрано в пуле",
    "img_lbl_expenses": "Оплата ЭЭ | Налог сети",
    "img_title_infra": "ИНФРАСТРУКТУРА",
    "img_lbl_gpus": "Видеокарт",
    "img_lbl_cooling": "Система охлада",
    "img_lbl_heat": "Тепловыделение ядра",
    "img_status_norm": "НОРМА",
    "img_status_high": "ПОВЫШЕННАЯ",
    "img_status_crit": "КРИТИЧЕСКАЯ",
    "img_title_status": "СОСТОЯНИЕ СИСТЕМЫ (STATUS)",
    "img_title_licenses": "ЛИЦЕНЗИИ",
    "img_no_licenses": "НЕТ АКТИВНЫХ ЛИЦЕНЗИЙ",
    "img_lbl_fiat_reserve": "СВОБОДНЫЙ ФИАТНЫЙ РЕЗЕРВ:",
    "img_fallback_agent": "АГЕНТ",
    "img_lbl_global_event": "АКТИВНОЕ ГЛОБАЛЬНОЕ СОБЫТИЕ"
}

def get_str(key: str, _=None, **kwargs) -> str:
    if _:
        return _(key, **kwargs)
    text = FALLBACK_STRINGS.get(key, key)
    if kwargs:
        try: return text.format(**kwargs)
        except: pass
    return text

# ==========================================
# 👤 ГЕНЕРАТОР ПРОФИЛЯ (ELITE ID + КРИПТА)
# ==========================================
def generate_html_profile(
    user_id: int, username: str, title: str, balance: int, gold_balance: int, 
    umc_balance: int, rating: int, clan_name: str, role_header: str, licenses: list, _=None
) -> str:
    
    title_display = title if title else get_str("img_reg_agent", _)
    rating_color = "#39ff14" if rating >= 2500 else "#ff003c"
    rating_width = min(100, max(5, int((rating / 5000) * 100))) 
    
    if licenses:
        licenses_html = "".join([f'<div class="list-item"><span class="bullet">◈</span> {lic}</div>' for lic in licenses])
    else:
        licenses_html = f'<div class="list-item empty">{get_str("img_db_empty", _)}</div>'

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght=500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
        <style>
            :root {{
                --gold: #ffc107;
                --gold-glow: rgba(255, 193, 7, 0.5);
                --dark-bg: #020408;
                --panel-bg: rgba(10, 15, 28, 0.7);
                --text-main: #f8fafc;
                --text-muted: #64748b;
                --accent-blue: #00d2ff;
                --accent-glow: rgba(0, 210, 255, 0.4);
                --crypto-cyan: #06b6d4;
            }}
            
            body {{
                margin: 0; padding: 20px; 
                background-color: var(--dark-bg);
                background-image: 
                    linear-gradient(rgba(0, 210, 255, 0.03) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(0, 210, 255, 0.03) 1px, transparent 1px);
                background-size: 25px 25px;
                font-family: 'Rajdhani', sans-serif; 
                color: var(--text-main);
                width: 760px; min-height: 940px; 
                box-sizing: border-box;
                display: flex; align-items: stretch;
            }}

            .card {{
                width: 100%; display: flex; flex-direction: column;
                background: linear-gradient(135deg, #060b13 0%, #03050a 100%);
                border: 1px solid rgba(0, 210, 255, 0.35); 
                padding: 35px; box-sizing: border-box;
                box-shadow: 0 0 50px rgba(0, 0, 0, 0.95), inset 0 0 35px rgba(0, 210, 255, 0.06);
                position: relative; border-radius: 12px; overflow: hidden;
            }}

            .card::after {{
                content: " "; display: block; position: absolute; top: 0; left: 0; bottom: 0; right: 0;
                background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.2) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.04), rgba(0, 255, 0, 0.01), rgba(0, 0, 255, 0.04));
                z-index: 2; background-size: 100% 3px, 4px 100%; pointer-events: none;
            }}

            .card::before {{
                content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px;
                background: linear-gradient(90deg, transparent, var(--gold), transparent);
                box-shadow: 0 0 25px var(--gold); z-index: 3;
            }}

            .content-wrapper {{ position: relative; z-index: 5; flex-grow: 1; display: flex; flex-direction: column; }}

            .id-badge {{
                position: absolute; top: -5px; right: 0px; 
                font-family: 'Share Tech Mono', monospace;
                font-size: 14px; color: var(--accent-blue); opacity: 0.85;
                letter-spacing: 2px; border-bottom: 1px solid rgba(0, 210, 255, 0.4); padding-bottom: 4px;
            }}

            .header-line {{ margin-bottom: 35px; text-align: left; }}
            
            .role-text {{
                font-size: 34px; color: var(--gold); font-weight: 700; letter-spacing: 4px;
                text-transform: uppercase; text-shadow: 0 0 25px var(--gold-glow);
                display: inline-block; border-left: 5px solid var(--gold); padding-left: 15px; line-height: 1;
            }}

            .wealth-container {{ display: flex; gap: 15px; margin-bottom: 30px; }}
            .wealth-panel {{
                flex: 1; background: rgba(3, 6, 12, 0.8); border: 1px solid rgba(255,255,255,0.05);
                padding: 20px; border-radius: 8px; position: relative;
                backdrop-filter: blur(12px);
            }}
            .wealth-panel.credits {{ border-bottom: 3px solid var(--gold); box-shadow: 0 8px 25px -10px var(--gold-glow); }}
            .wealth-panel.gold {{ border-bottom: 3px solid #fbbf24; box-shadow: 0 8px 25px -10px rgba(251, 191, 36, 0.25); }}
            .wealth-panel.crypto {{ border-bottom: 3px solid var(--crypto-cyan); box-shadow: 0 8px 25px -10px rgba(6, 182, 212, 0.25); }}
            
            .label {{ 
                color: var(--text-muted); font-size: 13px; text-transform: uppercase; 
                letter-spacing: 1.5px; margin-bottom: 10px; font-weight: 600; font-family: 'Share Tech Mono', monospace;
            }}
            
            .val-huge {{ font-size: 30px; font-weight: 700; line-height: 1; letter-spacing: 0.5px; }}
            .val-huge.credits {{ color: #fff; text-shadow: 0 0 15px rgba(255,255,255,0.25); }}
            .val-huge.credits span {{ color: var(--gold); font-size: 22px; }}
            .val-huge.gold {{ color: #fbbf24; text-shadow: 0 0 20px rgba(251, 191, 36, 0.35); }}
            .val-huge.crypto {{ color: var(--crypto-cyan); text-shadow: 0 0 20px rgba(6, 182, 212, 0.35); }}
            
            .grid {{ display: flex; gap: 20px; margin-bottom: 30px; }}
            
            .panel {{
                flex: 1; background: var(--panel-bg); border: 1px solid rgba(0, 210, 255, 0.15);
                padding: 22px; border-radius: 8px; backdrop-filter: blur(12px);
                box-shadow: inset 0 0 15px rgba(0, 210, 255, 0.03);
            }}
            
            .val {{ font-size: 26px; font-weight: 700; color: #fff; line-height: 1.2; }}
            .val.neon-green {{ color: #39ff14; text-shadow: 0 0 20px rgba(57, 255, 20, 0.45); }}
            
            .rating-box {{ margin-top: 5px; }}
            .rating-num {{ font-size: 28px; font-weight: 700; color: {rating_color}; text-shadow: 0 0 20px {rating_color}; }}
            .bar-bg {{ width: 100%; height: 8px; background: #070a12; margin-top: 12px; border-radius: 4px; overflow: hidden; border: 1px solid rgba(255,255,255,0.05); }}
            .bar-fill {{ 
                width: {rating_width}%; height: 100%; 
                background: linear-gradient(90deg, transparent, {rating_color}); 
                box-shadow: 0 0 15px {rating_color}; 
            }}

            .licenses {{
                background: rgba(2, 4, 8, 0.5); border: 1px dashed rgba(0, 210, 255, 0.3);
                padding: 25px; border-radius: 8px; flex-grow: 1; backdrop-filter: blur(12px);
            }}
            .licenses .label {{ color: var(--accent-blue); margin-bottom: 18px; text-shadow: 0 0 12px var(--accent-glow); font-size: 14px; }}
            
            .list-item {{ font-size: 19px; margin-bottom: 12px; color: #e2e8f0; font-weight: 500; display: flex; align-items: center; gap: 12px; }}
            .list-item .bullet {{ color: var(--gold); font-size: 15px; text-shadow: 0 0 12px var(--gold); }}
            .list-item.empty {{ color: var(--text-muted); font-family: 'Share Tech Mono', monospace; font-size: 16px; justify-content: center; margin-top: 20px; }}
            
        </style>
    </head>
    <body>
        <div class="card">
            <div class="content-wrapper">
                <div class="id-badge">SRC_CORE // SYSTEM_ID_{user_id}</div>
                
                <div class="header-line">
                    <div class="role-text">{role_header}</div>
                </div>
                
                <div class="wealth-container">
                    <div class="wealth-panel credits">
                        <div class="label">{get_str("img_lbl_credits", _)}</div>
                        <div class="val-huge credits">{fmt(balance)} <span>ᴜ</span></div>
                    </div>
                    <div class="wealth-panel crypto">
                        <div class="label">{get_str("img_lbl_crypto", _)}</div>
                        <div class="val-huge crypto">{fmt(umc_balance)} UMC</div>
                    </div>
                    <div class="wealth-panel gold">
                        <div class="label">{get_str("img_lbl_gold", _)}</div>
                        <div class="val-huge gold">{fmt(gold_balance)} UG</div>
                    </div>
                </div>
                
                <div class="grid">
                    <div class="panel">
                        <div class="label">{get_str("img_lbl_alias", _)}</div>
                        <div class="val" style="margin-bottom: 18px; font-size: 28px; letter-spacing: 1px; color: #ffffff;">{username.upper()}</div>
                        
                        <div class="label">{get_str("img_lbl_net_status", _)}</div>
                        <div class="val neon-green" style="font-size: 24px;">{title_display}</div>
                    </div>
                    
                    <div class="panel">
                        <div class="label">{get_str("img_lbl_standing", _)}</div>
                        <div class="rating-box" style="margin-bottom: 18px;">
                            <div class="rating-num">{fmt(rating)} PTS</div>
                            <div class="bar-bg"><div class="bar-fill"></div></div>
                        </div>
                        
                        <div class="label">{get_str("img_lbl_affiliation", _)}</div>
                        <div class="val" style="color: #a5b4fc; font-size: 24px;">{clan_name}</div>
                    </div>
                </div>
                
                <div class="licenses">
                    <div class="label">{get_str("img_lbl_clearances", _)}</div>
                    {licenses_html}
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    filename = f"profile_{user_id}.png"
    hti.screenshot(html_str=html_content, save_as=filename, size=(800, 1000))
    return filename


# ==========================================
# 🏭 ГЕНЕРАТОР ФЕРМЫ (ULTRA NEON + КРИПТА + ИВЕНТЫ)
# ==========================================
def generate_html_farm_dashboard(
    user_id: int, username: str, active_title: str, balance: int, 
    income_ph: int, heat: int, cooling: int, cards: int, 
    storage_val: int, power_ph: int, tax_percent: int, 
    cooling_name: str, farm_status: str, licenses: list,
    is_boosted: bool = False, current_event: str = "Нет", _=None  
) -> str:
    
    heat_ratio = heat / cooling if cooling > 0 else 1.0
    if heat_ratio <= 0.6:
        bar_color = "#10b981" 
        heat_status_text = get_str("img_status_norm", _)
    elif heat_ratio <= 0.9:
        bar_color = "#f59e0b" 
        heat_status_text = get_str("img_status_high", _)
    else:
        bar_color = "#ef4444" 
        heat_status_text = get_str("img_status_crit", _)
        
    heat_width = min(100, max(2, int(heat_ratio * 100)))
    title_display = active_title if active_title else get_str("img_fallback_agent", _)
    boost_icon = "🔥" if is_boosted else ""

    if licenses:
        licenses_html = "".join([f'<div class="lic-item"><span class="arr">◈</span> {lic}</div>' for lic in licenses])
    else:
        licenses_html = f'<div class="lic-item muted">{get_str("img_no_licenses", _)}</div>'

    # 🔥 РЕНДЕР ПЛАШКИ ГЛОБАЛЬНОГО СОБЫТИЯ
    event_html = ""
    if current_event and current_event != "Нет":
        event_html = f"""
        <div class="event-banner">
            <div class="event-lbl">{get_str("img_lbl_global_event", _)}</div>
            <div class="event-name">⚠️ {current_event.upper()}</div>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
        <style>
            :root {{
                --cyan: #06b6d4;
                --cyan-glow: rgba(6, 182, 212, 0.5);
                --gold: #fbbf24;
                --bg: #030712;
                --panel: rgba(11, 19, 36, 0.75);
                --text-main: #f8fafc;
                --text-muted: #64748b;
                --neon-red: #ef4444;
                --neon-green: #10b981;
                --orange-event: #ff7b00;
            }}

            body {{
                margin: 0; padding: 25px; 
                background-color: var(--bg);
                background-image: 
                    linear-gradient(rgba(6, 182, 212, 0.04) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(6, 182, 212, 0.04) 1px, transparent 1px);
                background-size: 20px 20px;
                font-family: 'Rajdhani', sans-serif; color: var(--text-main);
                width: 760px; min-height: 950px; box-sizing: border-box;
                display: flex; align-items: stretch;
            }}

            .terminal {{
                width: 100%; display: flex; flex-direction: column;
                background: linear-gradient(180deg, #040814 0%, #091124 100%);
                border: 1px solid rgba(6, 182, 212, 0.45); border-radius: 10px;
                box-shadow: 0 0 45px rgba(0, 0, 0, 0.95), inset 0 0 30px rgba(6, 182, 212, 0.12);
                position: relative; overflow: hidden;
            }}

            .terminal::after {{
                content: " "; display: block; position: absolute; top: 0; left: 0; bottom: 0; right: 0;
                background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.22) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.05), rgba(0, 255, 0, 0.01), rgba(0, 0, 255, 0.05));
                z-index: 2; background-size: 100% 3px, 3px 100%; pointer-events: none;
            }}

            .content-wrapper {{ position: relative; z-index: 5; display: flex; flex-direction: column; flex-grow: 1; }}

            .sys-header {{
                background: rgba(6, 182, 212, 0.15); border-bottom: 1px solid rgba(6, 182, 212, 0.5);
                padding: 12px 20px; display: flex; justify-content: space-between;
                font-family: 'Share Tech Mono', monospace; font-size: 14px; color: var(--cyan);
                text-transform: uppercase; letter-spacing: 2px; text-shadow: 0 0 10px var(--cyan-glow);
            }}

            .content {{ padding: 30px; flex-grow: 1; display: flex; flex-direction: column; }}

            .top-bar {{
                border-bottom: 2px dashed rgba(6, 182, 212, 0.25);
                padding-bottom: 15px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: flex-end;
            }}

            .title-box .main {{
                color: var(--cyan); font-size: 24px; font-weight: 700; letter-spacing: 3px;
                text-shadow: 0 0 15px var(--cyan-glow); margin-bottom: 6px;
            }}
            .title-box .user {{ font-size: 32px; font-weight: 700; color: #fff; line-height: 1; text-shadow: 0 0 10px rgba(255,255,255,0.25); }}
            .title-box .tag {{ color: var(--gold); font-size: 19px; vertical-align: middle; margin-left: 10px; text-shadow: 0 0 10px rgba(251, 191, 36, 0.4); }}

            .event-banner {{
                background: linear-gradient(90deg, rgba(255, 123, 0, 0.15) 0%, transparent 100%);
                border-left: 5px solid var(--orange-event); padding: 12px 20px; margin-bottom: 20px;
                box-shadow: inset 0 0 15px rgba(255, 123, 0, 0.02); border-radius: 0 6px 6px 0;
            }}
            .event-lbl {{ color: var(--orange-event); font-family: 'Share Tech Mono', monospace; font-size: 12px; font-weight: 600; letter-spacing: 1.5px; margin-bottom: 4px; }}
            .event-name {{ font-size: 22px; font-weight: 700; color: #fff; letter-spacing: 1px; text-shadow: 0 0 15px rgba(255, 123, 0, 0.4); }}

            .income-banner {{
                background: linear-gradient(90deg, rgba(16, 185, 129, 0.12) 0%, transparent 100%);
                border-left: 5px solid var(--neon-green); padding: 20px; margin-bottom: 28px;
                backdrop-filter: blur(6px);
            }}
            .income-banner .lbl {{ color: var(--neon-green); font-family: 'Share Tech Mono', monospace; font-size: 14px; margin-bottom: 6px; text-shadow: 0 0 8px rgba(16,185,129,0.4); }}
            .income-banner .val {{ font-size: 54px; font-weight: 700; color: #fff; text-shadow: 0 0 25px rgba(16,185,129,0.4); line-height: 1; }}
            .income-banner .val span {{ font-size: 30px; color: var(--neon-green); }}

            .grid {{ display: flex; gap: 20px; margin-bottom: 28px; }}
            
            .panel {{
                flex: 1; background: var(--panel); border: 1px solid rgba(6, 182, 212, 0.2);
                padding: 25px; border-radius: 8px; position: relative; backdrop-filter: blur(12px);
                box-shadow: inset 0 0 15px rgba(6, 182, 212, 0.02);
            }}
            .panel-title {{
                position: absolute; top: -12px; left: 15px; background: var(--cyan); color: #020617;
                padding: 2px 12px; font-size: 13px; font-weight: 700; font-family: 'Share Tech Mono', monospace;
                box-shadow: 0 0 12px var(--cyan-glow); border-radius: 3px;
            }}

            .data-row {{ margin-bottom: 18px; }}
            .data-row:last-child {{ margin-bottom: 0; }}
            .lbl {{ color: var(--text-muted); font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 6px; font-weight: 600; font-family: 'Share Tech Mono', monospace; }}
            .val {{ font-size: 26px; font-weight: 700; color: #fff; line-height: 1.1; }}
            
            .val.storage {{ color: var(--cyan); text-shadow: 0 0 15px rgba(6, 182, 212, 0.35); }}
            .val.expense {{ color: var(--neon-red); font-size: 23px; text-shadow: 0 0 15px rgba(239, 68, 68, 0.35); }}
            .val.tech {{ font-family: 'Share Tech Mono', monospace; color: #cbd5e1; }}

            .heat-bar-bg {{ width: 100%; height: 12px; background: #060b14; border-radius: 4px; overflow: hidden; border: 1px solid #1e293b; margin-top: 10px; box-shadow: inset 0 0 8px #000; }}
            .heat-bar-fill {{ width: {heat_width}%; height: 100%; background: {bar_color}; box-shadow: 0 0 15px {bar_color}; }}
            .heat-info {{ display: flex; justify-content: space-between; margin-top: 10px; font-family: 'Share Tech Mono', monospace; font-size: 14px; }}
            .heat-info .status {{ color: {bar_color}; font-weight: 700; text-shadow: 0 0 10px {bar_color}; }}

            .bottom-grid {{ display: flex; gap: 20px; flex-grow: 1; margin-bottom: 15px; }}
            
            .status-box {{
                flex: 1.4; background: rgba(2, 4, 8, 0.4); border: 1px dashed rgba(6, 182, 212, 0.3);
                padding: 22px; border-radius: 8px; display: flex; flex-direction: column; justify-content: center;
                backdrop-filter: blur(12px);
            }}
            .sys-status {{ font-size: 23px; font-weight: 700; margin-top: 6px; letter-spacing: 0.5px; }}
            
            .licenses-box {{
                flex: 1; padding-left: 20px; border-left: 2px solid rgba(255,255,255,0.06);
            }}
            .lic-item {{ font-size: 18px; color: #e2e8f0; margin-bottom: 8px; font-weight: 500; display: flex; align-items: center; }}
            .lic-item .arr {{ color: var(--cyan); font-size: 13px; margin-right: 8px; text-shadow: 0 0 8px var(--cyan); }}
            .lic-item.muted {{ color: var(--text-muted); font-size: 14px; font-family: 'Share Tech Mono', monospace; margin-top: 12px; }}

            .balance-footer {{
                background: rgba(2, 4, 8, 0.85); border-top: 2px solid var(--gold); padding: 22px 30px;
                display: flex; justify-content: space-between; align-items: center;
                box-shadow: 0 -8px 25px rgba(251, 191, 36, 0.12);
            }}
            .balance-footer .text {{ color: var(--text-muted); font-size: 15px; text-transform: uppercase; letter-spacing: 2.5px; font-weight: 700; font-family: 'Share Tech Mono', monospace; }}
            .balance-footer .sum {{ color: var(--gold); font-size: 34px; font-weight: 700; text-shadow: 0 0 25px rgba(251, 191, 36, 0.5); }}
        </style>
    </head>
    <body>
        <div class="terminal">
            <div class="content-wrapper">
                <div class="sys-header">
                    <span>[ CORE_NODE // LINK_ID: 88X-OMEGA ]</span>
                    <span>SECURE BLOCKCHAIN CONNECTION TRACED</span>
                </div>
                
                <div class="content">
                    <div class="top-bar">
                        <div class="title-box">
                            <div class="main">{get_str("img_farm_title", _)}</div>
                            <div class="user">{username.upper()} <span class="tag">[{title_display}]</span></div>
                        </div>
                    </div>
                    
                    {event_html}
                    
                    <div class="income-banner">
                        <div class="lbl">{get_str("img_lbl_hashrate", _)}</div>
                        <div class="val">+{fmt(income_ph)} <span>UMC/h</span> {boost_icon}</div>
                    </div>
                    
                    <div class="grid">
                        <div class="panel">
                            <div class="panel-title">{get_str("img_title_finances", _)}</div>
                            <div class="data-row">
                                <div class="lbl">{get_str("img_lbl_collected", _)}</div>
                                <div class="val storage">~{fmt(storage_val)} UMC</div>
                            </div>
                            <div class="data-row">
                                <div class="lbl">{get_str("img_lbl_expenses", _)}</div>
                                <div class="val expense">-{fmt(power_ph)} <b>ᴜ/h</b> <span style="color: #64748b; font-size: 18px; font-family: 'Share Tech Mono';">| {tax_percent}%</span></div>
                            </div>
                        </div>
                        
                        <div class="panel">
                            <div class="panel-title">{get_str("img_title_infra", _)}</div>
                            <div class="data-row" style="display: flex; justify-content: space-between;">
                                <div>
                                    <div class="lbl">{get_str("img_lbl_gpus", _)}</div>
                                    <div class="val tech" style="font-size: 24px;">{cards} pcs</div>
                                </div>
                                <div style="text-align: right;">
                                    <div class="lbl">{get_str("img_lbl_cooling", _)}</div>
                                    <div class="val tech" style="font-size: 18px; color: var(--cyan);">{cooling_name}</div>
                                </div>
                            </div>
                            <div class="data-row">
                                <div class="lbl">{get_str("img_lbl_heat", _)}</div>
                                <div class="heat-bar-bg"><div class="heat-bar-fill"></div></div>
                                <div class="heat-info">
                                    <span>{fmt(heat)} / {fmt(cooling)} HU</span>
                                    <span class="status">{heat_status_text}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="bottom-grid">
                        <div class="status-box">
                            <div class="lbl">{get_str("img_title_status", _)}</div>
                            <div class="sys-status">{farm_status}</div>
                        </div>
                        <div class="licenses-box">
                            <div class="lbl" style="color: var(--gold); margin-bottom: 15px;">{get_str("img_title_licenses", _)}</div>
                            {licenses_html}
                        </div>
                    </div>
                </div>
                
                <div class="balance-footer">
                    <div class="text">{get_str("img_lbl_fiat_reserve", _)}</div>
                    <div class="sum">{fmt(balance)} ᴜ</div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    filename = f"farm_{user_id}.png"
    hti.screenshot(html_str=html_content, save_as=filename, size=(800, 1000))
    return filename