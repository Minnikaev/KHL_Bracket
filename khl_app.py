import csv
import os
from datetime import datetime

import pandas as pd
import streamlit as st
import json
import gspread
from google.oauth2.service_account import Credentials

def get_gsheet():
    service_account_info = dict(st.secrets["gcp_service_account"])

    creds = Credentials.from_service_account_info(
        service_account_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )

    client = gspread.authorize(creds)
    spreadsheet = client.open("KHL Bracket Submissions")
    return spreadsheet.sheet1


# =========================
# CONFIG
# =========================
TEAMS_FILE = "teams.csv"
SUBMISSIONS_FILE = "submissions.csv"
ACTUAL_RESULTS_FILE = "actual_results.csv"

ROUND_1_FIELDS = [
    "r1_west_1", "r1_west_2", "r1_west_3", "r1_west_4",
    "r1_east_1", "r1_east_2", "r1_east_3", "r1_east_4",
]
QF_FIELDS = ["qf_1", "qf_2", "qf_3", "qf_4"]
SF_FIELDS = ["sf_1", "sf_2"]
FINAL_FIELDS = ["champion"]

ALL_RESULT_FIELDS = ROUND_1_FIELDS + QF_FIELDS + SF_FIELDS + FINAL_FIELDS


# =========================
# PAGE SETTINGS
# =========================
st.set_page_config(
    page_title="KHL Bracket Challenge",
    page_icon="🏒",
    layout="wide"
)

st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }
    .subtitle {
        color: #6b7280;
        margin-bottom: 1.2rem;
    }
    .section-title {
        font-size: 1.2rem;
        font-weight: 700;
        margin-bottom: 0.8rem;
        margin-top: 0.3rem;
    }
    .round-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 14px 14px 10px 14px;
        margin-bottom: 14px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }
    .match-label {
        font-size: 0.82rem;
        color: #6b7280;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        margin-bottom: 8px;
    }
    .team-line {
        font-size: 0.97rem;
        font-weight: 600;
        margin-bottom: 4px;
    }
    .versus-line {
        font-size: 0.85rem;
        color: #9ca3af;
        margin: 6px 0;
    }
    .leaderboard-title {
        font-size: 1.25rem;
        font-weight: 700;
        margin-top: 1rem;
        margin-bottom: 0.8rem;
    }
    .footer-note {
        color: #6b7280;
        font-size: 0.9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# DATA LOADING
# =========================
def load_teams_from_csv(file_path=TEAMS_FILE):
    teams = []

    with open(file_path, mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            teams.append({
                "team": row["team"],
                "conference": row["conference"],
                "seed": int(row["seed"])
            })

    return teams


def validate_teams(teams):
    if len(teams) != 16:
        raise ValueError("В файле teams.csv должно быть ровно 16 команд.")

    west = [team for team in teams if team["conference"] == "West"]
    east = [team for team in teams if team["conference"] == "East"]

    if len(west) != 8 or len(east) != 8:
        raise ValueError("Должно быть ровно 8 команд Запада и 8 команд Востока.")

    west_seeds = sorted(team["seed"] for team in west)
    east_seeds = sorted(team["seed"] for team in east)

    if west_seeds != list(range(1, 9)):
        raise ValueError("У Запада seeds должны быть от 1 до 8 без пропусков.")

    if east_seeds != list(range(1, 9)):
        raise ValueError("У Востока seeds должны быть от 1 до 8 без пропусков.")


def load_submissions():
    sheet = get_gsheet()
    data = sheet.get_all_records()

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    return df


def load_actual_results(file_path=ACTUAL_RESULTS_FILE):
    if not os.path.exists(file_path):
        return {}

    df = pd.read_csv(file_path)

    if df.empty:
        return {}

    row = df.iloc[0].to_dict()

    cleaned = {}
    for field in ALL_RESULT_FIELDS:
        value = row.get(field, "")
        if pd.isna(value):
            value = ""
        cleaned[field] = str(value).strip()

    return cleaned


# =========================
# BRACKET LOGIC
# =========================
def get_conference_teams(team_list, conference):
    return sorted(
        [team for team in team_list if team["conference"] == conference],
        key=lambda x: x["seed"]
    )


def get_first_round_pairings(team_list):
    west = get_conference_teams(team_list, "West")
    east = get_conference_teams(team_list, "East")

    def make_pairs(conf_teams):
        return [
            (conf_teams[0], conf_teams[7]),
            (conf_teams[1], conf_teams[6]),
            (conf_teams[2], conf_teams[5]),
            (conf_teams[3], conf_teams[4]),
        ]

    return {
        "West": make_pairs(west),
        "East": make_pairs(east)
    }


def get_second_round_pairings(first_round_winners):
    west = get_conference_teams(first_round_winners, "West")
    east = get_conference_teams(first_round_winners, "East")

    return [
        (west[0], east[3]),
        (east[0], west[3]),
        (west[1], east[2]),
        (east[1], west[2]),
    ]


def get_semifinal_pairings(second_round_winners):
    return [
        (second_round_winners[0], second_round_winners[2]),
        (second_round_winners[1], second_round_winners[3]),
    ]


def get_final_pairing(semifinal_winners):
    return (semifinal_winners[0], semifinal_winners[1])


# =========================
# HELPERS
# =========================
def clear_predictions():
    keys_to_delete = [
        key for key in st.session_state.keys()
        if key.startswith("pick_") or key == "participant_name"
    ]
    for key in keys_to_delete:
        del st.session_state[key]


def participant_exists(participant_name, file_path=SUBMISSIONS_FILE):
    if not os.path.exists(file_path):
        return False

    df = pd.read_csv(file_path)

    if df.empty or "participant_name" not in df.columns:
        return False

    normalized_input = str(participant_name).strip().lower()
    normalized_names = (
        df["participant_name"]
        .astype(str)
        .str.strip()
        .str.lower()
    )

    return normalized_input in set(normalized_names)


def save_submission(submission):
    sheet = get_gsheet()

    values = [
        submission["timestamp"],
        submission["participant_name"],
        submission["r1_west_1"],
        submission["r1_west_2"],
        submission["r1_west_3"],
        submission["r1_west_4"],
        submission["r1_east_1"],
        submission["r1_east_2"],
        submission["r1_east_3"],
        submission["r1_east_4"],
        submission["qf_1"],
        submission["qf_2"],
        submission["qf_3"],
        submission["qf_4"],
        submission["sf_1"],
        submission["sf_2"],
        submission["champion"],
    ]

    sheet.append_row(values)


def non_empty_values(row_dict, fields):
    values = set()

    for field in fields:
        value = row_dict.get(field, "")
        if pd.isna(value):
            value = ""
        value = str(value).strip()
        if value:
            values.add(value)

    return values


def calculate_score(submission_row, actual_results):
    score = 0

    predicted_r1 = non_empty_values(submission_row, ROUND_1_FIELDS)
    actual_r1 = non_empty_values(actual_results, ROUND_1_FIELDS)
    score += len(predicted_r1 & actual_r1) * 1

    predicted_qf = non_empty_values(submission_row, QF_FIELDS)
    actual_qf = non_empty_values(actual_results, QF_FIELDS)
    score += len(predicted_qf & actual_qf) * 2

    predicted_sf = non_empty_values(submission_row, SF_FIELDS)
    actual_sf = non_empty_values(actual_results, SF_FIELDS)
    score += len(predicted_sf & actual_sf) * 4

    predicted_champion = str(submission_row.get("champion", "")).strip()
    actual_champion = str(actual_results.get("champion", "")).strip()
    if actual_champion and predicted_champion == actual_champion:
        score += 8

    return score


def get_stage_hits(submission_row, actual_results):
    return {
        "r1_hits": len(non_empty_values(submission_row, ROUND_1_FIELDS) & non_empty_values(actual_results, ROUND_1_FIELDS)),
        "qf_hits": len(non_empty_values(submission_row, QF_FIELDS) & non_empty_values(actual_results, QF_FIELDS)),
        "sf_hits": len(non_empty_values(submission_row, SF_FIELDS) & non_empty_values(actual_results, SF_FIELDS)),
        "champion_hit": int(
            str(submission_row.get("champion", "")).strip() != ""
            and str(submission_row.get("champion", "")).strip() == str(actual_results.get("champion", "")).strip()
            and str(actual_results.get("champion", "")).strip() != ""
        )
    }


def build_leaderboard(submissions_df, actual_results):
    if submissions_df.empty:
        return pd.DataFrame()

    leaderboard_rows = []

    for _, row in submissions_df.iterrows():
        row_dict = row.to_dict()
        hits = get_stage_hits(row_dict, actual_results)
        score = calculate_score(row_dict, actual_results)

        leaderboard_rows.append({
            "Имя": row_dict.get("participant_name", ""),
            "Очки": score,
            "R1": hits["r1_hits"],
            "QF": hits["qf_hits"],
            "SF": hits["sf_hits"],
            "Чемпион": hits["champion_hit"],
            "Время отправки": row_dict.get("timestamp", pd.NaT),
        })

    leaderboard_df = pd.DataFrame(leaderboard_rows)

    leaderboard_df = leaderboard_df.sort_values(
        by=["Очки", "SF", "QF", "R1", "Время отправки"],
        ascending=[False, False, False, False, True]
    ).reset_index(drop=True)

    leaderboard_df.index = leaderboard_df.index + 1
    leaderboard_df.insert(0, "Место", leaderboard_df.index)

    return leaderboard_df


def get_progress_text(actual_results):
    r1_done = len(non_empty_values(actual_results, ROUND_1_FIELDS))
    qf_done = len(non_empty_values(actual_results, QF_FIELDS))
    sf_done = len(non_empty_values(actual_results, SF_FIELDS))
    champion_done = 1 if str(actual_results.get("champion", "")).strip() else 0

    return f"Подтверждено результатов: R1 {r1_done}/8 · QF {qf_done}/4 · SF {sf_done}/2 · Champion {champion_done}/1"


def team_label(team):
    return f"({team['seed']}) {team['team']}"


def render_match_card(pair, key_prefix, label):
    team1, team2 = pair

    st.markdown("<div class='round-card'>", unsafe_allow_html=True)
    st.markdown(f"<div class='match-label'>{label}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='team-line'>{team_label(team1)}</div>", unsafe_allow_html=True)
    st.markdown("<div class='versus-line'>vs</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='team-line'>{team_label(team2)}</div>", unsafe_allow_html=True)

    selected_team_name = st.radio(
        label,
        options=[team1["team"], team2["team"]],
        key=f"pick_{key_prefix}",
        label_visibility="collapsed"
    )

    st.markdown("</div>", unsafe_allow_html=True)

    return team1 if selected_team_name == team1["team"] else team2


def add_space(lines=1):
    for _ in range(lines):
        st.write("")


# =========================
# LOAD DATA
# =========================
try:
    teams = load_teams_from_csv(TEAMS_FILE)
    validate_teams(teams)
except Exception as e:
    st.error(f"Ошибка загрузки teams.csv: {e}")
    st.stop()

actual_results = load_actual_results(ACTUAL_RESULTS_FILE)
submissions_df = load_submissions()


# =========================
# HEADER
# =========================
st.markdown("<div class='main-title'>KHL Bracket Challenge</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='subtitle'>Заполни сетку до старта плей-офф. Очки обновляются автоматически по ходу турнира.</div>",
    unsafe_allow_html=True
)

top1, top2, top3 = st.columns([1.4, 1, 1])

with top1:
    participant_name = st.text_input("Твоё имя", key="participant_name", placeholder="Например, Mur")

with top2:
    st.write("")
    if st.button("Сбросить выборы", use_container_width=True):
        clear_predictions()
        st.rerun()

with top3:
    st.write("")
    save_clicked = st.button("Сохранить брекет", type="primary", use_container_width=True)

st.caption(get_progress_text(actual_results))


# =========================
# BUILD BRACKET
# =========================
first_round = get_first_round_pairings(teams)
first_round_winners = []

col_r1, col_r2, col_sf, col_f = st.columns([1.6, 1.3, 1.1, 1])

with col_r1:
    st.markdown("<div class='section-title'>Первый раунд</div>", unsafe_allow_html=True)
    st.caption("Запад")
    for i, pair in enumerate(first_round["West"], start=1):
        winner = render_match_card(pair, key_prefix=f"r1_west_{i}", label=f"W{i}")
        first_round_winners.append(winner)

    add_space(1)
    st.caption("Восток")
    for i, pair in enumerate(first_round["East"], start=1):
        winner = render_match_card(pair, key_prefix=f"r1_east_{i}", label=f"E{i}")
        first_round_winners.append(winner)

second_round = get_second_round_pairings(first_round_winners)
second_round_winners = []

with col_r2:
    st.markdown("<div class='section-title'>Второй раунд</div>", unsafe_allow_html=True)
    add_space(2)
    for i, pair in enumerate(second_round, start=1):
        winner = render_match_card(pair, key_prefix=f"qf_{i}", label=f"QF{i}")
        second_round_winners.append(winner)
        add_space(1)

semifinals = get_semifinal_pairings(second_round_winners)
semifinal_winners = []

with col_sf:
    st.markdown("<div class='section-title'>Полуфиналы</div>", unsafe_allow_html=True)
    add_space(5)
    for i, pair in enumerate(semifinals, start=1):
        winner = render_match_card(pair, key_prefix=f"sf_{i}", label=f"SF{i}")
        semifinal_winners.append(winner)
        add_space(4)

final_pair = get_final_pairing(semifinal_winners)

with col_f:
    st.markdown("<div class='section-title'>Финал</div>", unsafe_allow_html=True)
    add_space(9)
    champion = render_match_card(final_pair, key_prefix="final", label="Final")

st.success(f"🏆 Твой чемпион: {champion['team']}")


# =========================
# SAVE ACTION
# =========================
if save_clicked:
    cleaned_name = participant_name.strip()

    if not cleaned_name:
        st.error("Введи имя перед сохранением.")
    else:
        already_exists = participant_exists(cleaned_name, SUBMISSIONS_FILE)

        submission = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "participant_name": cleaned_name,
            "r1_west_1": first_round_winners[0]["team"],
            "r1_west_2": first_round_winners[1]["team"],
            "r1_west_3": first_round_winners[2]["team"],
            "r1_west_4": first_round_winners[3]["team"],
            "r1_east_1": first_round_winners[4]["team"],
            "r1_east_2": first_round_winners[5]["team"],
            "r1_east_3": first_round_winners[6]["team"],
            "r1_east_4": first_round_winners[7]["team"],
            "qf_1": second_round_winners[0]["team"],
            "qf_2": second_round_winners[1]["team"],
            "qf_3": second_round_winners[2]["team"],
            "qf_4": second_round_winners[3]["team"],
            "sf_1": semifinal_winners[0]["team"],
            "sf_2": semifinal_winners[1]["team"],
            "champion": champion["team"],
        }

        save_submission(submission

        if already_exists:
            st.success("Старый брекет для этого имени заменён новым.")
        else:
            st.success("Брекет сохранён.")

        st.rerun()


# =========================
# MY BRACKET SUMMARY
# =========================
st.markdown("<div class='leaderboard-title'>Твой текущий выбор</div>", unsafe_allow_html=True)

sum1, sum2, sum3, sum4 = st.columns(4)

with sum1:
    st.markdown("**R1**")
    st.write(", ".join([winner["team"] for winner in first_round_winners[:4]]))
    st.write(", ".join([winner["team"] for winner in first_round_winners[4:]]))

with sum2:
    st.markdown("**QF**")
    st.write(", ".join([winner["team"] for winner in second_round_winners]))

with sum3:
    st.markdown("**SF**")
    st.write(", ".join([winner["team"] for winner in semifinal_winners]))

with sum4:
    st.markdown("**Champion**")
    st.write(champion["team"])


# =========================
# LEADERBOARD
# =========================
st.markdown("<div class='leaderboard-title'>Текущая таблица</div>", unsafe_allow_html=True)

if submissions_df.empty:
    st.info("Пока ещё нет сохранённых брекетов.")
else:
    leaderboard_df = build_leaderboard(submissions_df, actual_results)

    m1, m2, m3 = st.columns(3)
    m1.metric("Всего отправок", len(submissions_df))
    m2.metric("Участников", submissions_df["participant_name"].nunique())
    m3.metric("Лидер", leaderboard_df.iloc[0]["Имя"] if not leaderboard_df.empty else "—")

    st.dataframe(
        leaderboard_df[["Место", "Имя", "Очки"]],
        use_container_width=True,
        hide_index=True
    )

st.markdown(
    "<div class='footer-note'>Чужие выборы и чемпионы скрыты. В таблице видны только место, имя и очки.</div>",
    unsafe_allow_html=True
)
