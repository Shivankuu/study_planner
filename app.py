import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import streamlit_authenticator as stauth
import matplotlib.pyplot as plt
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- DEBUG INFO ---
st.write("📌 App Reloaded")

# --- AUTHENTICATION CONFIGURATION ---
credentials = {
    "usernames": {
        "john": {
            "name": "John Doe",
            "password": "$2b$12$MSSgzVgXbOkk.ZmTFtfspu6C18P1TFP8m96aGoSAqL6JDdxCBsZRO",  # '123'
            "email": "john@example.com"
        },
        "alice": {
            "name": "Alice Smith",
            "password": "$2b$12$29ylg1RHp/7wCUyDqynvCOEFw6zUkA/vSKddpdBFBB8y7fa7bQacO",  # 'abc'
            "email": "alice@example.com"
        }
    }
}

# --- AUTHENTICATOR SETUP ---
authenticator = stauth.Authenticate(
    credentials,
    cookie_name="studyplanner_app",  # Ensure same name on every run
    key="abcdef",  # Consistent key
    cookie_expiry_days=30
)

# --- LOGIN ---
name, authentication_status, username = authenticator.login(form_name="Login", location="main")


# Debug login state
st.write("Auth status:", authentication_status)
st.write("Logged in user:", username)

# --- GOOGLE SHEETS AUTH ---
def get_gsheet_client():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Google Sheets Auth Error: {e}")
        return None

# --- STUDY PLAN GENERATOR FUNCTION ---
def generate_study_plan(subject_difficulties, study_hours_per_day, deadline, time_slots):
    today = datetime.now().date()
    days_remaining = (deadline - today).days

    if days_remaining <= 0 or study_hours_per_day <= 0 or not subject_difficulties or not time_slots:
        return pd.DataFrame()

    total_hours = study_hours_per_day * days_remaining
    total_difficulty = sum(subject_difficulties.values())

    subject_total_hours = {
        subject: (difficulty / total_difficulty) * total_hours
        for subject, difficulty in subject_difficulties.items()
    }

    subject_daily_hours = {
        subject: round(hours / days_remaining, 2)
        for subject, hours in subject_total_hours.items()
    }

    plan = []
    revisions = {subject: [] for subject in subject_difficulties}

    for i in range(days_remaining):
        date = today + timedelta(days=i)
        day_plan = {"Date": date}
        available_slots = [{
            "start": datetime.combine(date, slot_start),
            "end": datetime.combine(date, slot_end)
        } for slot_start, slot_end in time_slots]

        for subject, required_hours in subject_daily_hours.items():
            allocated = 0
            time_allocations = []

            for slot in available_slots:
                if allocated >= required_hours:
                    break
                slot_duration = (slot["end"] - slot["start"]).seconds / 3600
                alloc_time = min(required_hours - allocated, slot_duration)
                if alloc_time <= 0:
                    continue
                start_time = slot["start"]
                end_time = start_time + timedelta(hours=alloc_time)
                time_allocations.append(f"{start_time.time().strftime('%H:%M')} - {end_time.time().strftime('%H:%M')}")
                slot["start"] = end_time
                allocated += alloc_time

            if allocated < required_hours:
                time_allocations.append("⚠️ Not enough time")

            day_plan[subject] = " / ".join(time_allocations)

            for revision_gap in [2, 4, 7, 15]:
                revision_day = date + timedelta(days=revision_gap)
                if revision_day <= deadline:
                    revisions[subject].append(revision_day)

        plan.append(day_plan)

    for revision_date in sorted({d for sublist in revisions.values() for d in sublist}):
        if revision_date <= deadline:
            rev_day_plan = {"Date": revision_date}
            for subject in subject_difficulties:
                if revision_date in revisions[subject]:
                    rev_day_plan[subject] = "🔁 Revision"
            plan.append(rev_day_plan)

    plan.sort(key=lambda x: x["Date"])
    return pd.DataFrame(plan)

# --- EMAIL FUNCTION ---
def send_email_schedule(receiver_email, today_plan, user_name):
    try:
        sender_email = st.secrets["email"]["sender_email"]
        sender_password = st.secrets["email"]["app_password"]
    except Exception as e:
        st.error("Please check your email secrets configuration!")
        return False

    subject = f"📅 Study Plan for Today - {user_name}"
    body = f"Hello {user_name},\n\nHere is your study plan for today:\n\n"
    for subject, time_slots in today_plan.items():
        if subject != "Date":
            body += f"{subject}: {time_slots}\n"
    body += "\nGood luck with your studies! 📚"

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, message.as_string())
        return True
    except Exception as e:
        st.error(f"Email error: {e}")
        return False

# --- MAIN APP ---
if authentication_status:
    st.sidebar.success(f"Welcome, {name}!")
    authenticator.logout("Logout", "sidebar")
    st.title("📚 Personalized AI-Based Study Planner")

    user_name = st.text_input("Enter your name:")
    study_hours = st.slider("How many hours can you study daily?", 1, 12, 4)
    subject_input = st.text_area("Enter subjects separated by commas:")
    deadline = st.date_input("Select your exam/deadline date:")

    st.subheader("Select Study Time Slots")
    time_slots = []
    for i in range(3):
        start_time = st.time_input(f"Start Time for Slot {i + 1}", key=f"start_{i}")
        end_time = st.time_input(f"End Time for Slot {i + 1}", key=f"end_{i}")
        if start_time and end_time and end_time > start_time:
            time_slots.append((start_time, end_time))

    subject_difficulties = {}
    if subject_input:
        subject_list = list(filter(None, [s.strip() for s in subject_input.split(",")]))
        st.subheader("Rate Difficulty for Each Subject (1 = Easy, 5 = Hard)")
        for subject in subject_list:
            difficulty = st.slider(f"{subject}", 1, 5, 3, key=f"diff_{subject}")
            subject_difficulties[subject] = difficulty

    plan_df = None
    if st.button("Generate Study Plan"):
        if user_name and subject_difficulties and time_slots:
            plan_df = generate_study_plan(subject_difficulties, study_hours, deadline, time_slots)
            if not plan_df.empty:
                st.dataframe(plan_df)

                st.subheader("✅ Daily Checklist")
                today_str = str(datetime.now().date())
                if today_str in plan_df["Date"].astype(str).values:
                    today_tasks = plan_df[plan_df["Date"].astype(str) == today_str].iloc[0]
                    for subject in plan_df.columns[1:]:
                        st.checkbox(f"{subject}: {today_tasks[subject]}")
                else:
                    st.info("No plan for today.")

                st.subheader("📊 Study Time Distribution")
                subject_totals = {}
                for subject in plan_df.columns[1:]:
                    total_minutes = 0
                    for slot in plan_df[subject]:
                        for part in str(slot).split("/"):
                            times = part.strip().split(" - ")
                            if len(times) == 2:
                                try:
                                    start = datetime.strptime(times[0], "%H:%M")
                                    end = datetime.strptime(times[1], "%H:%M")
                                    total_minutes += (end - start).seconds // 60
                                except:
                                    pass
                    subject_totals[subject] = total_minutes / 60

                fig, ax = plt.subplots()
                ax.bar(subject_totals.keys(), subject_totals.values(), color='skyblue')
                ax.set_ylabel("Total Study Hours")
                ax.set_title("Study Time Allocation per Subject")
                st.pyplot(fig)

                if st.button("📤 Save to Google Sheet"):
                    client = get_gsheet_client()
                    if client:
                        try:
                            sheet = client.open("StudyPlannerData").sheet1
                            sheet.clear()
                            sheet.update([plan_df.columns.tolist()] + plan_df.values.tolist())
                            st.success("Saved to Google Sheets!")
                        except Exception as e:
                            st.error(f"Sheet error: {e}")

                if st.button("📥 Load from Google Sheet"):
                    client = get_gsheet_client()
                    if client:
                        try:
                            sheet = client.open("StudyPlannerData").sheet1
                            data = sheet.get_all_records()
                            if data:
                                loaded_df = pd.DataFrame(data)
                                st.dataframe(loaded_df)
                        except Exception as e:
                            st.error(f"Load error: {e}")
        else:
            st.warning("Please fill all required details.")

    if st.button("📧 Send Today’s Plan via Email"):
        if 'plan_df' in locals() and plan_df is not None:
            today_str = str(datetime.now().date())
            if today_str in plan_df["Date"].astype(str).values:
                today_tasks = plan_df[plan_df["Date"].astype(str) == today_str].iloc[0].to_dict()
                if send_email_schedule(credentials["usernames"][username]["email"], today_tasks, user_name):
                    st.success("Email sent successfully!")
            else:
                st.info("No plan available for today.")
        else:
            st.warning("Generate your study plan first.")

    st.subheader("⏳ Pomodoro Timer")
    pomodoro_duration = st.number_input("Pomodoro Duration (minutes)", 10, 60, 25)
    break_duration = st.number_input("Break Duration (minutes)", 5, 30, 5)

    if st.button("Start Pomodoro"):
        st.success("Pomodoro started! Stay focused 💪")
        countdown = pomodoro_duration * 60
        timer_placeholder = st.empty()
        for remaining in range(countdown, 0, -1):
            mins, secs = divmod(remaining, 60)
            timer_placeholder.markdown(f"### ⏰ Time Left: {mins:02d}:{secs:02d}")
            time.sleep(1)
        st.balloons()
        st.success("Pomodoro done! Time for a break 🍵")

elif authentication_status is False:
    st.error("Incorrect username or password.")
elif authentication_status is None:
    st.warning("Please enter your credentials to continue.")

# --- REGISTRATION / PASSWORD RESET ---
with st.expander("🔑 Not registered or forgot password?"):
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Register New User"):
            try:
                authenticator.register_user()
                st.success("User registered successfully!")
            except Exception as e:
                st.error(f"Error registering: {e}")
    with col2:
        if st.button("Reset Password"):
            try:
                authenticator.reset_password()
                st.success("Password reset successfully!")
            except Exception as e:
                st.error(f"Error resetting password: {e}")

























