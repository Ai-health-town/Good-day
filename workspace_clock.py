"""A small Riyadh clock; ticks locally without rerunning the app or its queries."""

import streamlit as st


CLOCK = """
<style>
.gday-timebar{display:flex;justify-content:flex-start;direction:rtl;width:100%;padding:0 0 10px;}
.gday-clock{display:flex;align-items:center;gap:18px;max-width:100%;padding:14px 19px;border:1px solid #e1e8e8;border-radius:16px;background:linear-gradient(115deg,#fff 35%,#eff8f5 100%);box-shadow:0 3px 14px #203c3505;font-family:'IBM Plex Sans Arabic',sans-serif;color:#203840;}
.gday-clock-symbol{display:grid;place-items:center;width:39px;height:39px;flex:none;border-radius:12px;background:#e2f2ec;color:#13897b;}
.gday-clock-glyph{position:relative;display:block;width:21px;height:21px;border:1.7px solid currentColor;border-radius:50%;}
.gday-clock-glyph::before{content:'';position:absolute;left:8px;top:3px;width:1.5px;height:6px;background:currentColor;border-radius:2px;}
.gday-clock-glyph::after{content:'';position:absolute;left:8px;top:8px;width:6px;height:1.5px;background:currentColor;border-radius:2px;transform:rotate(35deg);transform-origin:left center;}
.gday-clock-digital{min-width:112px;text-align:center;}
.gday-clock-time{display:flex;align-items:baseline;justify-content:center;direction:ltr;unicode-bidi:isolate;white-space:nowrap;font-variant-numeric:tabular-nums;line-height:1.2;}
.gday-clock-hm{font-size:27px;font-weight:700;letter-spacing:-.6px;}
.gday-clock-seconds{font-size:16px;font-weight:500;color:#13897b;}
.gday-clock-period{font-size:12px;color:#69817d;margin-left:5px;}
.gday-clock-zone{display:flex;gap:5px;align-items:center;justify-content:center;font-size:10px;color:#7a8b8b;margin-top:5px;white-space:nowrap;}
.gday-clock-dot{width:5px;height:5px;border-radius:50%;background:#30ae92;}
.gday-clock-divider{height:39px;width:1px;flex:none;background:#dce7e3;}
.gday-clock-calendar{min-width:0;text-align:right;}
.gday-clock-day{font-size:13px;font-weight:700;color:#28534c;line-height:1.5;margin-bottom:4px;}
.gday-clock-dates{display:flex;align-items:center;gap:9px;flex-wrap:wrap;font-size:11px;color:#78878e;line-height:1.8;}
.gday-clock-dates time{white-space:nowrap;unicode-bidi:isolate;}
.gday-clock-hijri{color:#45675f;font-weight:500;}
.gday-clock-date-dot{color:#b7c4c0;}
@media(max-width:800px){.gday-clock{gap:12px;padding:12px 15px;}.gday-clock-dates{gap:6px;}}
@media(max-width:520px){.gday-clock{width:100%;gap:11px;padding:12px;}.gday-clock-symbol{display:none;}.gday-clock-digital{min-width:101px;}.gday-clock-hm{font-size:25px;}.gday-clock-dates{display:flex;flex-direction:column;align-items:flex-start;gap:0;}.gday-clock-date-dot{display:none;}.gday-clock-divider{height:48px;}.gday-clock-day{font-size:12px;margin-bottom:2px;}}
</style>
<div class="gday-timebar">
  <section id="gday-workspace-clock" class="gday-clock" dir="rtl" aria-label="الوقت والتاريخ بتوقيت الرياض">
    <div class="gday-clock-symbol" aria-hidden="true">
      <span class="gday-clock-glyph"></span>
    </div>
    <div class="gday-clock-digital">
      <time class="gday-clock-time" aria-live="off" dir="ltr"><span class="gday-clock-hm">—:—</span><span class="gday-clock-seconds"></span><span class="gday-clock-period"></span></time>
      <div class="gday-clock-zone"><span class="gday-clock-dot" aria-hidden="true"></span>بتوقيت الرياض</div>
    </div>
    <span class="gday-clock-divider" aria-hidden="true"></span>
    <div class="gday-clock-calendar">
      <div class="gday-clock-day">اليوم</div>
      <div class="gday-clock-dates">
        <time class="gday-clock-hijri" aria-label="التاريخ الهجري — تقويم أم القرى">— هـ</time>
        <span class="gday-clock-date-dot" aria-hidden="true">•</span>
        <time class="gday-clock-gregorian" aria-label="التاريخ الميلادي">— م</time>
      </div>
    </div>
  </section>
</div>
<script>
(() => {
  const root = document.getElementById('gday-workspace-clock');
  if (!root) return;
  if (root.gdayTimer) clearInterval(root.gdayTimer);
  const options = {timeZone:'Asia/Riyadh', numberingSystem:'arab'};
  const clock = new Intl.DateTimeFormat('ar-SA', {...options, calendar:'gregory', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:true});
  const day = new Intl.DateTimeFormat('ar-SA', {...options, calendar:'gregory', weekday:'long'});
  const gregorian = new Intl.DateTimeFormat('ar-SA', {...options, calendar:'gregory', day:'numeric', month:'long', year:'numeric'});
  const hijri = new Intl.DateTimeFormat('ar-SA', {...options, calendar:'islamic-umalqura', day:'numeric', month:'long', year:'numeric'});
  const key = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Riyadh', calendar:'gregory', year:'numeric', month:'2-digit', day:'2-digit'});
  const time = root.querySelector('.gday-clock-time');
  const hm = root.querySelector('.gday-clock-hm');
  const seconds = root.querySelector('.gday-clock-seconds');
  const period = root.querySelector('.gday-clock-period');
  const weekday = root.querySelector('.gday-clock-day');
  const hijriDate = root.querySelector('.gday-clock-hijri');
  const gregorianDate = root.querySelector('.gday-clock-gregorian');
  const parts = (formatter, value) => Object.fromEntries(formatter.formatToParts(value).map(part => [part.type,part.value]));
  const dateText = (formatter, value, era) => {
    const p = parts(formatter,value);
    return `${p.day} ${p.month} ${p.year} ${era}`;
  };
  let lastDay = '';
  const tick = () => {
    const now = new Date();
    const p = parts(clock,now);
    hm.textContent = `${p.hour}:${p.minute}`;
    seconds.textContent = `:${p.second}`;
    period.textContent = p.dayPeriod;
    time.dateTime = now.toISOString();
    time.setAttribute('aria-label', `${p.hour}:${p.minute}:${p.second} ${p.dayPeriod} بتوقيت الرياض`);
    const today = key.format(now);
    if (today !== lastDay) {
      weekday.textContent = day.format(now);
      hijriDate.textContent = dateText(hijri,now,'هـ');
      gregorianDate.textContent = dateText(gregorian,now,'م');
      hijriDate.dateTime = today;
      gregorianDate.dateTime = today;
      lastDay = today;
    }
  };
  tick();
  root.gdayTimer = setInterval(() => {
    if (!root.isConnected) {clearInterval(root.gdayTimer); return;}
    tick();
  },1000);
})();
</script>
"""


def render_clock():
    # This is constant application code; no member input or credentials enter it.
    st.html(CLOCK, unsafe_allow_javascript=True)
