# Proshield Reports - מערכת דיווח שטח

מערכת PWA לדיווח שטח עבור אספקות והתקנות, עם תמיכה בעברית ו-RTL.

## תכונות עיקריות

- **דיווח אספקות והתקנות** - יצירת דוחות שטח עם כל הפרטים הנדרשים
- **בחירת מוצרים** - רשימת מוצרים עם כמויות
- **העלאת תמונות** - צילום או העלאת תמונות מרובות
- **תעודות משלוח** - העלאת תעודות משלוח חתומות (PDF/תמונה)
- **עבודה offline** - שמירת דוחות מקומית וסנכרון אוטומטי
- **ניהול משתמשים** - מערכת הרשאות עם מנהל ומשתמשים רגילים
- **יצוא לאקסל** - ייצוא דוחות לקובץ Excel

## דרישות מערכת

- Python 3.9 ומעלה
- דפדפן מודרני (Chrome, Firefox, Safari, Edge)

## התקנה והפעלה

### Windows

1. פתח את התיקייה `proshield-reports`
2. לחץ כפול על `run.bat`
3. המתן להתקנת התלויות
4. פתח בדפדפן: http://localhost:5000

### Linux/Mac

```bash
cd proshield-reports
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

## כניסה ראשונה

**משתמש מנהל ברירת מחדל:**
- שם משתמש: `rotem`
- סיסמה: `proshield2025`

## מבנה הפרויקט

```
proshield-reports/
├── app.py              # Flask application
├── models.py           # Database models
├── config.py           # Configuration
├── run.py              # Run script
├── run.bat             # Windows batch file
├── requirements.txt    # Python dependencies
├── templates/          # HTML templates
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── new_report.html
│   ├── view_report.html
│   ├── settings.html
│   └── admin.html
├── static/
│   ├── css/style.css   # Main stylesheet
│   ├── js/app.js       # JavaScript
│   ├── js/sw.js        # Service Worker
│   ├── manifest.json   # PWA manifest
│   └── images/         # Icons
├── uploads/            # Uploaded files
│   └── reports/
└── instance/
    └── proshield.db    # SQLite database
```

## יצירת דוח חדש

1. לחץ על "דוח חדש"
2. בחר סוג דוח (אספקה/התקנה)
3. הזן כתובת
4. בחר מוצרים והזן כמויות
5. בחר סטטוס (הושלם/נדרש חזרה)
6. העלה תמונות
7. העלה תעודת משלוח (אספקה בלבד)
8. הוסף הערות (אופציונלי)
9. לחץ "שמור דוח"

## התקנה כאפליקציה (PWA)

### Android
1. פתח את האתר בדפדפן Chrome
2. לחץ על כפתור "התקן" או על התראת ההתקנה
3. האפליקציה תופיע במסך הבית

### iOS
1. פתח את האתר ב-Safari
2. לחץ על כפתור השיתוף
3. בחר "הוסף למסך הבית"

## פריסה בשרת

### עם Gunicorn (מומלץ)

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### עם Nginx

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /uploads {
        alias /path/to/proshield-reports/uploads;
    }
}
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

## אבטחה

- כל הסיסמאות מוצפנות עם bcrypt
- הגנה מפני SQL injection
- הגנה מפני XSS
- ניהול sessions מאובטח
- הגבלת גודל קבצים

## רשימת מוצרים

- Floorliner - Vapor Shield
- Floorliner - Original Shield
- Allprotect - White Shield
- Allprotect - Original
- Allprotect - Flex
- Allprotect - Original cut to 20cm
- Allprotect - Flex cut to 10cm/15cm/17cm/20cm/25cm
- PP Tape
- סרט דבק
- זווית פינה קשיחה
- פרופיל L מוקצף 18/45/120 מ"מ

## תמיכה

לשאלות ותמיכה, פנה לצוות הפיתוח.

## גרסה

1.0.0 - February 2026
