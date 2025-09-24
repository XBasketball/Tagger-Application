import streamlit as st
import pandas as pd
from datetime import datetime, date
from collections import defaultdict
import re
import time


st.set_page_config(page_title="StFx Mens Basketball Tagger", layout="wide")

# ---------------------------
# Roster (EDIT THIS LIST)
# ---------------------------
# Put your roster here (strings shown in the Player picker)
ROSTER = [
    "DJ Jackson", "Matt Pennell", "Koat Thomas", "Nic Naire", "Jeff Ngandu",
    "Phoenyx Wyse", "Tariq Armstrong", "Will Tong", "Tim Bilek", "Jayden Webley",
    "Dakoda Lewis", "Gabe Marcotullio"
]

# ---------------------------
# Session State & Utilities
# ---------------------------
def init_state():
    st.session_state.setdefault("plays", [])               # list[str]
    st.session_state.setdefault("log", [])                 # list[dict]
    st.session_state.setdefault("selected_play", None)     # str | None
    st.session_state.setdefault("opponent", "")
    st.session_state.setdefault("game_date", date.today())
    st.session_state.setdefault("quarter", "")
    st.session_state.setdefault("new_play", "")

    # --- NEW: roster & selection
    st.session_state.setdefault("selected_player", ROSTER[0] if ROSTER else "")

    # --- NEW: clock state
    st.session_state.setdefault("q_minutes", 10)        # regulation quarter length (minutes)
    st.session_state.setdefault("ot_minutes", 5)        # OT length (minutes)
    st.session_state.setdefault("clock_running", False)
    st.session_state.setdefault("clock_elapsed", 0.0)   # seconds elapsed in current period
    st.session_state.setdefault("clock_started_at", None)  # time.monotonic() when started

def safe_filename(s: str) -> str:
    s = s.strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_\-\.]", "", s)
    return s

def points_from_result(result: str) -> int:
    return {"Made 2": 2, "Made 3": 3, "Missed 2": 0, "Missed 3": 0, "Foul": 0}.get(result, 0)

# --- NEW: Clock helpers
def _period_duration_seconds() -> int:
    """Return total seconds for the current period (quarter or OT)."""
    q = st.session_state["quarter"]
    minutes = st.session_state["ot_minutes"] if q == "OT" else st.session_state["q_minutes"]
    try:
        minutes = int(minutes)
    except Exception:
        minutes = 10
    return max(0, minutes) * 60

def _effective_elapsed_seconds() -> float:
    """Elapsed seconds in this period, including in-flight time if running."""
    elapsed = st.session_state["clock_elapsed"]
    if st.session_state["clock_running"] and st.session_state["clock_started_at"] is not None:
        elapsed += (time.monotonic() - st.session_state["clock_started_at"])
    # clamp between 0 and period duration
    return max(0.0, min(elapsed, float(_period_duration_seconds())))

def current_clock_remaining() -> int:
    """Return remaining whole seconds on the game clock (counting down)."""
    total = _period_duration_seconds()
    elapsed = _effective_elapsed_seconds()
    remaining = int(round(total - elapsed))
    return max(0, remaining)

def format_mmss(seconds: int) -> str:
    m = seconds // 60
    s = seconds % 60
    return f"{m:01d}:{s:02d}"

def start_clock():
    if not st.session_state["clock_running"]:
        st.session_state["clock_started_at"] = time.monotonic()
        st.session_state["clock_running"] = True

def stop_clock():
    if st.session_state["clock_running"]:
        # accumulate elapsed
        if st.session_state["clock_started_at"] is not None:
            st.session_state["clock_elapsed"] += (time.monotonic() - st.session_state["clock_started_at"])
        st.session_state["clock_started_at"] = None
        st.session_state["clock_running"] = False

def reset_clock_to_full():
    """Reset period clock back to full duration."""
    st.session_state["clock_running"] = False
    st.session_state["clock_started_at"] = None
    st.session_state["clock_elapsed"] = 0.0

def set_clock_from_mmss(mm: int, ss: int):
    """Set the clock to a specific remaining time (mm:ss)."""
    total = _period_duration_seconds()
    remaining = max(0, min(mm * 60 + ss, total))
    # Convert desired remaining → elapsed
    st.session_state["clock_running"] = False
    st.session_state["clock_started_at"] = None
    st.session_state["clock_elapsed"] = float(total - remaining)

def add_log(play: str, result: str):
    # NEW: capture player and game clock at the moment of tagging
    clock_str = format_mmss(current_clock_remaining())
    st.session_state["log"].append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "opponent": st.session_state["opponent"],
        "game_date": str(st.session_state["game_date"]),
        "quarter": st.session_state["quarter"],
        "clock": clock_str,                                # NEW
        "play": play,
        "result": result,
        "player": st.session_state["selected_player"],     # NEW
        "points": points_from_result(result),
    })

def compute_metrics(log_df: pd.DataFrame) -> pd.DataFrame:
    if log_df.empty:
        return pd.DataFrame(columns=["Play", "Attempts", "Points", "PPP", "Frequency", "Success Rate"])

    # Attempts = every tag (includes fouls)
    attempts = log_df.groupby("play").size().rename("Attempts")

    # Points
    points = log_df.groupby("play")["points"].sum().rename("Points")

    metrics = pd.concat([attempts, points], axis=1).reset_index().rename(columns={"play": "Play"})
    metrics["PPP"] = metrics["Points"] / metrics["Attempts"]

    total_attempts = metrics["Attempts"].sum()
    metrics["Frequency"] = metrics["Attempts"] / (total_attempts if total_attempts else 1)

    made_mask = log_df["result"].isin(["Made 2", "Made 3"])
    att_mask = log_df["result"].isin(["Made 2", "Made 3", "Missed 2", "Missed 3"])
    made_counts = log_df[made_mask].groupby("play").size()
    shot_attempts = log_df[att_mask].groupby("play").size()

    def success_rate(play_name):
        made = int(made_counts.get(play_name, 0))
        atts = int(shot_attempts.get(play_name, 0))
        return (made / atts) if atts else 0.0

    metrics["Success Rate"] = metrics["Play"].map(success_rate)

    metrics = metrics.sort_values(by=["PPP", "Attempts"], ascending=[False, False]).reset_index(drop=True)
    return metrics

init_state()

# ---------------------------
# Sidebar: Game Setup, Playbook & Clock Settings
# ---------------------------
st.sidebar.header("Game Setup")
st.session_state["opponent"] = st.sidebar.text_input("Opponent", value=st.session_state["opponent"])
st.session_state["game_date"] = st.sidebar.date_input("Game Date", value=st.session_state["game_date"])

quarters = ["", "1", "2", "3", "4", "OT"]
q_index = quarters.index(st.session_state["quarter"]) if st.session_state["quarter"] in quarters else 0
new_q = st.sidebar.selectbox("Quarter", quarters, index=q_index)

# If quarter changed, reset the clock to full for the new period
if new_q != st.session_state["quarter"]:
    st.session_state["quarter"] = new_q
    reset_clock_to_full()

ready_to_tag = bool(st.session_state["opponent"] and st.session_state["game_date"] and st.session_state["quarter"])

st.sidebar.markdown("---")
st.sidebar.subheader("Clock Settings")
st.session_state["q_minutes"] = st.sidebar.number_input("Quarter Length (min)", min_value=1, max_value=20, value=int(st.session_state["q_minutes"]))
st.session_state["ot_minutes"] = st.sidebar.number_input("OT Length (min)", min_value=1, max_value=20, value=int(st.session_state["ot_minutes"]))
if st.sidebar.button("Reset Clock to Full Period"):
    reset_clock_to_full()

st.sidebar.markdown("---")
st.sidebar.subheader("Playbook")
st.session_state["new_play"] = st.sidebar.text_input("New Play Name", value=st.session_state["new_play"])

def add_play():
    raw = st.session_state["new_play"].strip()
    if not raw:
        return
    # case-insensitive dedupe
    existing_lower = {p.lower() for p in st.session_state["plays"]}
    if raw.lower() in existing_lower:
        st.sidebar.warning("Play already exists.")
        return
    st.session_state["plays"].append(raw)
    st.session_state["new_play"] = ""

if st.sidebar.button("ADD NEW PLAY", use_container_width=True):
    add_play()

if st.session_state["plays"]:
    st.sidebar.caption("Current plays:")
    for p in st.session_state["plays"]:
        st.sidebar.write(f"• {p}")

st.sidebar.markdown("---")
if st.sidebar.button("Reset Game (clears log & selections)", type="secondary"):
    st.session_state["log"] = []
    st.session_state["selected_play"] = None
    st.success("Game state cleared.")

# ---------------------------
# Main: Tagging, Player, Clock & Metrics
# ---------------------------
st.title("StFx Mens Basketball Tagger")

if not ready_to_tag:
    st.warning("Select Opponent, Game Date, and Quarter in the sidebar to begin tagging.")
    st.stop()
else:
    st.write(f"**Game:** vs **{st.session_state['opponent']}** | **Date:** {st.session_state['game_date']} | **Quarter:** {st.session_state['quarter']}")

# --- Player buttons (sticky selection + instant visual update)
st.subheader("Assign Player")

if not ROSTER:
    st.error("No roster defined. Please edit the ROSTER list in the code.")
else:
    cols_per_row = 6
    rows = (len(ROSTER) + cols_per_row - 1) // cols_per_row
    idx = 0
    for r in range(rows):
        row_cols = st.columns(cols_per_row)
        for c in range(cols_per_row):
            if idx >= len(ROSTER):
                break
            name = ROSTER[idx]
            label = f"{'✅ ' if name == st.session_state.get('selected_player') else ''}{name}"
            if row_cols[c].button(label, key=f"player_btn_{idx}", use_container_width=True):
                st.session_state["selected_player"] = name
                st.rerun()  # ← force immediate redraw so the checkmark updates right away
            idx += 1

# --- NEW: Clock UI
st.subheader("Game Clock")
clock_cols = st.columns([2, 1, 1, 1, 2])
with clock_cols[0]:
    st.metric("Time Remaining", format_mmss(current_clock_remaining()))
with clock_cols[1]:
    if st.button("Start", use_container_width=True):
        # avoid starting past zero
        if current_clock_remaining() > 0:
            start_clock()
with clock_cols[2]:
    if st.button("Stop", use_container_width=True):
        stop_clock()
with clock_cols[3]:
    if st.button("Full Reset", use_container_width=True):
        reset_clock_to_full()
with clock_cols[4]:
    with st.popover("Set Time (mm:ss)"):
        mm = st.number_input("Minutes", min_value=0, max_value=59, value=current_clock_remaining() // 60, key="set_mm")
        ss = st.number_input("Seconds", min_value=0, max_value=59, value=current_clock_remaining() % 60, key="set_ss")
        if st.button("Apply", use_container_width=True):
            set_clock_from_mmss(int(mm), int(ss))
            st.toast(f"Clock set to {format_mmss(current_clock_remaining())}")

# Lightweight auto-refresh while the clock is running (once per second)
if st.session_state.get("clock_running"):
    st_autorefresh(interval=1000, key="clock_refresh")

# Play buttons grid
if not st.session_state["plays"]:
    st.info("Add at least one play in the sidebar to start tagging.")
else:
    st.subheader("Select a Play")
    cols_per_row = 4
    rows = (len(st.session_state["plays"]) + cols_per_row - 1) // cols_per_row
    idx = 0
    for r in range(rows):
        row_cols = st.columns(cols_per_row)
        for c in range(cols_per_row):
            if idx >= len(st.session_state["plays"]):
                break
            play = st.session_state["plays"][idx]
            if row_cols[c].button(play, key=f"play_btn_{idx}", use_container_width=True):
                st.session_state["selected_play"] = play
            idx += 1

# Tagging actions for selected play
if st.session_state["selected_play"]:
    st.markdown(f"**Tagging:** `{st.session_state['selected_play']}` → **{st.session_state['selected_player']}**  |  ⏱ {format_mmss(current_clock_remaining())}")
    a, b, c, d, e, f = st.columns(6)
    if a.button("Made 2", key="act_m2", use_container_width=True):
        add_log(st.session_state["selected_play"], "Made 2")
    if b.button("Made 3", key="act_m3", use_container_width=True):
        add_log(st.session_state["selected_play"], "Made 3")
    if c.button("Missed 2", key="act_x2", use_container_width=True):
        add_log(st.session_state["selected_play"], "Missed 2")
    if d.button("Missed 3", key="act_x3", use_container_width=True):
        add_log(st.session_state["selected_play"], "Missed 3")
    if e.button("Foul", key="act_fl", use_container_width=True):
        add_log(st.session_state["selected_play"], "Foul")
    if f.button("Undo Last", key="undo_last", use_container_width=True):
        if st.session_state["log"]:
            st.session_state["log"].pop()
            st.toast("Last tag removed.")
        else:
            st.toast("No tags to undo.", icon="⚠️")

st.markdown("---")

# Build DataFrames
log_df = pd.DataFrame(st.session_state["log"])
metrics_df = compute_metrics(log_df) if not log_df.empty else pd.DataFrame(columns=["Play", "Attempts", "Points", "PPP", "Frequency", "Success Rate"])

# Metrics table
st.subheader("📊 Per Play Metrics")
if metrics_df.empty:
    st.info("No data yet — tag some plays to see metrics.")
else:
    st.dataframe(
        metrics_df.style.format({
            "PPP": "{:.2f}",
            "Frequency": "{:.1%}",
            "Success Rate": "{:.1%}"
        }),
        use_container_width=True,
        hide_index=True
    )

    # Quick visuals
    left, right = st.columns(2)
    with left:
        st.caption("PPP by Play")
        st.bar_chart(metrics_df.set_index("Play")["PPP"], use_container_width=True)
    with right:
        st.caption("Frequency by Play")
        st.bar_chart(metrics_df.set_index("Play")["Frequency"], use_container_width=True)

# Play-by-play table
st.subheader("🧾 Play-by-Play Log")
if log_df.empty:
    st.info("No events logged yet.")
else:
    # Show useful columns first
    col_order = ["timestamp", "opponent", "game_date", "quarter", "clock", "play", "result", "player", "points"]
    for c in col_order:
        if c not in log_df.columns:
            col_order.remove(c)
    st.dataframe(log_df[col_order], use_container_width=True, hide_index=True)

# Exports
st.subheader("📥 Export")
if st.button("Prepare Exports"):
    st.session_state["__exports_ready"] = True

if st.session_state.get("__exports_ready") and not log_df.empty:
    opp = safe_filename(str(st.session_state["opponent"]))
    gdt = safe_filename(str(st.session_state["game_date"]))
    qtr = safe_filename(str(st.session_state["quarter"]))

    metrics_csv = metrics_df.to_csv(index=False).encode("utf-8")
    log_csv = log_df.to_csv(index=False).encode("utf-8")
    json_blob = log_df.to_json(orient="records", indent=2).encode("utf-8")

    st.download_button(
        "Download Per-Play Metrics (CSV)",
        data=metrics_csv,
        file_name=f"{opp}_{gdt}_Q{qtr}_metrics.csv",
        mime="text/csv",
        use_container_width=True
    )
    st.download_button(
        "Download Play-by-Play (CSV)",
        data=log_csv,
        file_name=f"{opp}_{gdt}_Q{qtr}_playbyplay.csv",
        mime="text/csv",
        use_container_width=True
    )
    st.download_button(
        "Download Snapshot (JSON)",
        data=json_blob,
        file_name=f"{opp}_{gdt}_Q{qtr}_snapshot.json",
        mime="application/json",
        use_container_width=True
    )
