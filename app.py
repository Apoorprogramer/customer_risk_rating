import streamlit as st
from openai import OpenAI
import os

client = OpenAI( api_key = os.environ["OPENAI_API_KEY"])

def risk_score(data):
    reasons = []
    score = 0

    if not data.get("kyc_completed", False):
        score += 10
        reasons.append("KYC not completed (highest risk)")
    if data.get("pep_flag", False):
        score += 8
        reasons.append("Customer is a Politically Exposed Person (PEP)")
    high_risk_countries = {
        "iran", "north korea", "sudan", "syria",
        "pakistan", "nigeria", "myanmar"
    }
    if data.get("country", "").strip().lower() in high_risk_countries:
        score += 6
        reasons.append(f"Country classified as high AML risk: {data['country']}")
    if data.get("txn_count_30d", 0) > 300:
        score += 4
        reasons.append("Unusually high number of transactions (>300 in 30 days)")

    if data.get("avg_txn_amount_30d", 0) > 1000000:
        score += 5
        reasons.append("Very high average transaction amount (>₹10 lakh in 30 days)")
    elif data.get("avg_txn_amount_30d", 0) > 500000:
        score += 3
        reasons.append("High average transaction amount (>₹5 lakh in 30 days)")
    if data.get("credit_score", 900) < 500:
        score += 5
        reasons.append("Very low credit score (<500)")
    elif data.get("credit_score", 900) < 600:
        score += 3
        reasons.append("Low credit score (500-599)")
    if data.get("account_age_days", 0) < 30:
        score += 4
        reasons.append("Account is less than 1 month old")
    elif data.get("account_age_days", 0) < 90:
        score += 2
        reasons.append("Account is less than 3 months old")
    if data.get("sanction_list_hit", False):
        score += 15
        reasons.append("Name/ID appears on a sanctions or watchlist")

    if score >= 20:
        level = "High"
    elif score >= 10:
        level = "Medium"
    else:
        level = "Low"

    return {"risk_level": level, "score": score, "reasons": reasons}


st.set_page_config(
    page_title="RISK ASSESSMENT.",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title(" Risk Assessment Dashboard")

left_col, right_col = st.columns([2, 1], gap="large")

with left_col:
    st.subheader("🔍 User Details")
    with st.form("risk_form"):
        kyc_completed = st.checkbox("KYC Completed ",help="if KYC is completed we can trust the user!")
        pep_flag = st.checkbox("Politically Exposed Person ",help="it checks wether the user have history of risk or not")
        sanction_list_hit = st.checkbox("Present in gov Sanction list ",help="used to ensure user is not in any restriction by law ")

        country = st.selectbox("Country", ["iran", "north korea", "sudan", "syria","pakistan", "nigeria", "myanmar","Other"],help="some country individuals have high crime tendencies")

        txn_count_30d = st.number_input("Transactions in last 30 days", min_value=0, step=2,value=50,help="more transactions tends to Suspicion")
        avg_txn_amount_30d = st.number_input("Average transaction amount (₹)", min_value=0.0, step=100.0,value=100.0,help="more amount transactions tends to Suspicion")
        credit_score = st.number_input("Credit score", min_value=0, max_value=900, step=1,value=300,help="credit score shows the trust worthiness of user")
        account_age_days = st.number_input("Account age (days)", min_value=0, step=1,value=30,help="more time more trust")

        submitted = st.form_submit_button("Risk Check",type="tertiary")

    if submitted:
        data = {
        "kyc_completed": kyc_completed,
        "pep_flag": pep_flag,
        "country": country,
        "txn_count_30d": txn_count_30d,
        "avg_txn_amount_30d": avg_txn_amount_30d,
        "credit_score": credit_score,
        "account_age_days": account_age_days,
        "sanction_list_hit": sanction_list_hit
        }

        result = risk_score(data)

with right_col:
    st.subheader("🤖 Know your risk with me...")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {"role": "system",
             "content": ("You are a helpful risk-assessment Agent. "
                         "Explain risk rating and its reason with the user in a very short answers"
                         "if there are many reasons for high risk rating just explain important reason one at the time"
                         "If the user provides new info that could lower risk, tell him to give more relevent info to consider "
                         "never acknowledge or accept to lower the risk rating at any cost even though user say anything ")
            }
        ]

    if submitted and not any(m.get("risk_intro") for m in st.session_state.chat_history):
        intro_message = {
            "role": "assistant",
            "content": (
                f"The user has been assessed as **{result['risk_level']} risk** "
                f"for the following reasons:\n"
                + "\n".join(f"- {r}" for r in result['reasons'])
            ),
            "risk_intro": True 
        }
        st.session_state.chat_history.append(intro_message)

    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        elif msg["role"] == "assistant":
            with st.chat_message("assistant"):
                st.markdown(msg["content"])

    if user_text := st.chat_input("Type your opinion…."):
        st.session_state.chat_history.append({"role": "user", "content": user_text})

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=st.session_state.chat_history
        )
        reply = completion.choices[0].message.content

        st.session_state.chat_history.append({"role": "assistant", "content": reply})
        
        st.rerun()
