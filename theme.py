"""G'day visual system: plum navigation, mint actions, clear Arabic typography."""
import html
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap');
:root{--ink:#18242d;--muted:#7e8792;--line:#e5e8ee;--mint:#087e77;--plum:#21152d;}
html,body,.stApp{font-family:'IBM Plex Sans Arabic',sans-serif;}
.stApp{background:#f5f6f9;color:var(--ink);}
.stMainBlockContainer{direction:rtl;max-width:1600px;padding:1.2rem 2.2rem 3rem;}
h1,h2,h3,h4,p,label,[data-testid=stMarkdownContainer],[data-testid=stCaptionContainer]{font-family:'IBM Plex Sans Arabic',sans-serif!important;}
h1{font-size:2rem!important;font-weight:700!important;letter-spacing:-.6px;}
h2{font-size:1.4rem!important;}h3{font-size:1.1rem!important;}
p{line-height:1.75;}[data-testid=stCaptionContainer]{color:var(--muted);}
header[data-testid=stHeader]{background:transparent;height:2.4rem;}
/* Hide hosting/source controls while retaining the sidebar's mobile toggle. */
[data-testid=stToolbar],[data-testid=stToolbarActions],[data-testid=stAppDeployButton],
#MainMenu,footer{display:none!important;}
section[data-testid=stSidebar]{direction:rtl;background:linear-gradient(180deg,#291b34,#191321);border:none;min-width:258px;max-width:285px;}
section[data-testid=stSidebar] h1,section[data-testid=stSidebar] h2,section[data-testid=stSidebar] h3,section[data-testid=stSidebar] p,
section[data-testid=stSidebar] label,section[data-testid=stSidebar] [data-testid=stCaptionContainer]{color:#d5cedd!important;}
section[data-testid=stSidebar] hr{border-color:#ffffff12;margin:1rem 0;}
section[data-testid=stSidebar] [data-testid=stRadio] label{padding:.4rem .7rem;border-radius:10px;}
section[data-testid=stSidebar] [data-testid=stRadio] label:has(input:checked){background:linear-gradient(90deg,#0e7d76,#0d6576);}
section[data-testid=stSidebar] [data-testid=stRadio] label:hover{background:#ffffff09;}
section[data-testid=stSidebar] [data-baseweb=select]>div{background:#ffffff0a;border-color:#ffffff19;color:#fff;}
section[data-testid=stSidebar] .stButton>button{background:#ffffff07;color:#e7e1ed;border-color:#ffffff16;}
section[data-testid=stSidebar] .stButton>button:hover{background:#ffffff12;border-color:#ffffff30;}
section[data-testid=stSidebar] [data-testid=stCheckbox] label{color:#d5cedd;}
.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button{border-radius:10px;min-height:2.4rem;font-weight:600;font-size:.84rem;transition:all .15s;}
.stButton>button{border-color:#dfe4e9;}
.stButton>button:hover{border-color:#81b7ad;box-shadow:0 2px 9px #10252107;}
button[kind=primary],button[kind=primaryFormSubmit]{background:var(--mint);border-color:var(--mint);color:white;}
button[kind=primary]:hover,button[kind=primaryFormSubmit]:hover{background:#096b65;color:white;border-color:#096b65;}
[data-testid=stTextInput] input,[data-testid=stTextArea] textarea{text-align:right;}
[data-testid=stTextArea] textarea{line-height:1.8;}
[data-testid=stTextInput]>div,[data-testid=stSelectbox]>div>div{border-radius:10px;}
[data-testid=stForm]{background:white;border:1px solid var(--line);border-radius:16px;padding:1.1rem;}
[data-testid=stExpander]{background:white;border-radius:14px;border-color:var(--line);}
[data-testid=stVerticalBlockBorderWrapper]>div{border-radius:16px!important;border-color:var(--line)!important;}
[data-testid=stMetric]{background:white;border:1px solid var(--line);border-radius:14px;padding:15px 20px;position:relative;}
[data-testid=stMetric]::after{content:'';position:absolute;top:16px;right:0;width:3px;height:24px;border-radius:3px;background:#16a394;}
[data-testid=stMetricValue]{font-size:1.9rem;font-weight:700;letter-spacing:-.4px;color:#203444;}
[data-testid=stMetricLabel]{font-size:.78rem;color:#7e8792;}
[data-testid=stDataFrame],[data-testid=stDataEditor]{border:1px solid var(--line);border-radius:14px;overflow:hidden;}
[data-testid=stCode]{direction:ltr;text-align:left;}
[data-testid=stChatMessage]{border:1px solid var(--line);border-radius:14px;background:#fff;}
[role=dialog]{direction:rtl;max-width:min(1080px,95vw);border-radius:22px;}
[role=dialog] [data-testid=stForm]{background:#f8f9fb;}
.st-key-masthead{padding:.2rem 0 .8rem;border-bottom:1px solid var(--line);margin-bottom:.7rem;}
.st-key-masthead h2{margin:0;padding:0;}.st-key-masthead p{margin:0;}
.brand{display:flex;align-items:center;gap:10px;padding:0 2px 5px;direction:ltr;justify-content:flex-start;}
.brand-mark{width:37px;height:37px;border-radius:11px;background:linear-gradient(140deg,#35ceae,#0d8ca2);display:grid;place-items:center;font-weight:700;color:white;box-shadow:0 6px 18px #0b827e30;font-size:17px;}
.brand-title{font-size:23px;font-weight:700;letter-spacing:-.9px;color:#fff;}.brand-pill{font-size:9px;letter-spacing:1px;border:1px solid #37bda84d;color:#5cdeca;border-radius:5px;padding:2px 5px;}
.section-label{font-size:10px;letter-spacing:1.3px;font-weight:600;color:#8f829e;padding:5px 2px;}
.side-person{display:flex;align-items:center;gap:10px;background:#ffffff06;padding:12px;border:1px solid #ffffff10;border-radius:12px;}
.avatar{border-radius:10px;width:34px;height:34px;background:#234d4c;color:#89e3c9;display:grid;place-items:center;font-weight:700;}
.side-person strong{font-size:13px;color:#eee9f2;}.side-person small{font-size:10px;color:#a99bb7;}
.welcome{background:linear-gradient(115deg,#f5f1fa 0%,#eff8f6 62%,#f9fcfb 100%);border:1px solid #e3e9e8;border-radius:18px;padding:25px 28px;margin:5px 0 18px;position:relative;overflow:hidden;}
.welcome::after{content:'✳';position:absolute;left:25px;top:-5px;font-size:120px;line-height:1.4;color:#0c89730b;font-family:serif;}
.welcome .eyebrow{font-size:10px;color:#778492;font-weight:600;letter-spacing:2px;}.welcome h1{font-size:27px!important;color:#1e3540;margin:7px 0 6px!important;padding:0!important;}
.welcome p{font-size:13px;color:#75838d;margin:0;max-width:80%;}
.eyebrow{font-size:10px;letter-spacing:1.6px;text-transform:uppercase;color:#94a0ad;font-weight:600;}
.panel-heading{display:flex;justify-content:space-between;align-items:center;margin:12px 0 10px;}.panel-heading strong{font-size:16px;}.panel-heading span{font-size:11px;color:#8d97a2;}
.focus-note{padding:18px 20px;background:#221b2d;color:#f1edf5;border-radius:16px;border:1px solid #30273e;margin:5px 0 16px;}
.focus-note .eyebrow{color:#66c9b6;}.focus-note p{font-size:13px;color:#eee9f2;line-height:1.8;margin:8px 0 3px;}
.empty-box{text-align:center;padding:40px 20px;background:#fff;border:1px dashed #d7e0e3;border-radius:16px;}.empty-box h3{color:#34424a;}.empty-box p{font-size:13px;color:#85929a;}
.task-meta{font-size:11px;color:#8c97a1;margin-top:4px;line-height:1.8;}.tag{display:inline-block;border-radius:6px;padding:2px 7px;font-size:10px;background:#eef4f4;color:#377a74;margin-left:5px;}
.tag.urgent{background:#fff0ef;color:#c65c56;}.tag.wait{background:#fff6df;color:#a68139;}.tag.done{background:#eaf6ef;color:#358060;}
.file-icon{width:38px;height:42px;display:flex;align-items:center;justify-content:center;border-radius:10px;background:#e7f0ff;color:#4874ad;font-size:11px;font-weight:700;}
.st-key-focus_card{border:1px solid #e2e7e8;background:white;border-radius:16px;padding:18px;}
.st-key-login_card{background:#fff;border:1px solid #e3e7eb;box-shadow:0 18px 60px #261d3410;border-radius:24px;padding:30px!important;}
.st-key-login_intro{padding:35px 15px 30px;}.st-key-login_intro h1{font-size:3.4rem!important;color:#242035;}.st-key-login_intro h3{font-size:1.5rem!important;}
.st-key-login_intro p{max-width:460px;color:#7b8190;line-height:2;font-size:15px;}
[data-testid=stPills] button{font-size:.8rem;border-radius:9px;}
@media(max-width:800px){.stMainBlockContainer{padding:1.4rem 1rem 3rem;}.welcome{padding:20px;}.welcome p{max-width:95%;}.welcome h1{font-size:23px!important;}.st-key-login_card{padding:20px!important;}}
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def safe(text):
    return html.escape(str(text or ""))


def welcome(name, subtitle, eyebrow="A CLEARER DAY STARTS HERE"):
    st.markdown(f'<div class="welcome"><div class="eyebrow">{safe(eyebrow)}</div><h1>أهلاً {safe(name)}، يومك أوضح ✳</h1><p>{safe(subtitle)}</p></div>', unsafe_allow_html=True)


def panel(title, sub=""):
    st.markdown(f'<div class="panel-heading"><strong>{safe(title)}</strong><span>{safe(sub)}</span></div>', unsafe_allow_html=True)


def empty(title, subtitle):
    st.markdown(f'<div class="empty-box"><h3>{safe(title)}</h3><p>{safe(subtitle)}</p></div>', unsafe_allow_html=True)
