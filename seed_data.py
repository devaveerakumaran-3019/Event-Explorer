from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to DB
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client['college_events']
events_col = db['events']

# Dummy Data
dummy_events = [
    {
        "title": "AI & ML Symposium 2026",
        "description": "A national level technical symposium focusing on the advancements in Artificial Intelligence and Machine Learning. Join us for paper presentations and keynotes.",
        "date": "2026-03-15",
        "time": "09:30 AM",
        "venue": "Main Auditorium, CIET",
        "category": "Technical",
        "image": "ai_event.jpg" # Ensure you have a placeholder image or it will use default
    },
    {
        "title": "Hack-a-Thon v4.0",
        "description": "24-hour coding marathon. Solve real-world problems, win exciting cash prizes up to ₹50,000. Open to all departments.",
        "date": "2026-04-10",
        "time": "08:00 AM",
        "venue": "CSE Lab Block A",
        "category": "Hackathon",
        "image": "hackathon.jpg"
    },
    {
        "title": "Cultural Fest: Takshashila",
        "description": "The biggest cultural gathering of the year. Dance, Music, Drama and DJ Night. Unleash your artistic side.",
        "date": "2026-05-20",
        "time": "05:00 PM",
        "venue": "Open Air Theatre",
        "category": "Cultural",
        "image": "cultural.jpg"
    }
]

# Insert
events_col.insert_many(dummy_events)
print("✅ Success! Added 3 dummy events to MongoDB.")