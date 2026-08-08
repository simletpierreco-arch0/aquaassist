<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AquaAssist Preview</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        body {
            margin: 0; font-family: 'Poppins', sans-serif;
            background: #F6FBFF; color: #33414F;
            display: flex; justify-content: center; align-items: center; height: 100vh;
        }
        /* The App Container */
        .app-window {
            width: 380px; height: 700px;
            background: white; border-radius: 30px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.15);
            overflow: hidden; position: relative;
            display: flex; flex-direction: column;
            border: 8px solid #333;
        }
        /* Blue Wave Header */
        .header {
            background: linear-gradient(135deg, #005A9C 0%, #0077CC 100%);
            padding: 30px 20px 50px 20px; color: white;
            position: relative; text-align: center;
        }
        .header h1 { margin: 0; font-size: 24px; font-weight: 800; }
        .header p { margin: 5px 0; font-size: 12px; opacity: 0.9; }
        .status-pill {
            background: rgba(255,255,255,0.2);
            padding: 4px 12px; border-radius: 20px;
            font-size: 10px; font-weight: bold; display: inline-block;
            margin-top: 10px; border: 1px solid rgba(255,255,255,0.3);
        }
        .wave {
            position: absolute; bottom: 0; left: 0; width: 100%; height: 30px;
            background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 320"><path fill="%23ffffff" d="M0,160L48,176C96,192,192,224,288,213.3C384,203,480,149,576,149.3C672,149,768,203,864,202.7C960,203,1056,149,1152,122.7C1248,96,1344,96,1392,96L1440,96L1440,320L1392,320C1344,320,1248,320,1152,320C1056,320,960,320,864,320C768,320,672,320,576,320C480,320,384,320,288,320C192,320,96,320,48,320L0,320Z"></path></svg>');
            background-size: cover;
        }
        /* Chat Area */
        .chat-area { flex: 1; padding: 20px; overflow-y: auto; background: #fdfdfd; }
        .msg { margin-bottom: 15px; max-width: 80%; padding: 12px; border-radius: 15px; font-size: 13px; line-height: 1.4; }
        .bot { background: #F0F7FF; color: #003B5C; border-bottom-left-radius: 2px; border: 1px solid #D1E9FF; }
        .user { background: #0077CC; color: white; margin-left: auto; border-bottom-right-radius: 2px; }
        /* Quick Actions */
        .quick-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 10px 20px; }
        .qa-btn {
            background: white; border: 1px solid #E0E8F0; padding: 10px;
            border-radius: 12px; font-size: 11px; font-weight: 600;
            text-align: center; cursor: pointer; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }
        /* Input Bar */
        .input-bar { padding: 15px 20px; border-top: 1px solid #EEE; display: flex; gap: 10px; }
        .input-field {
            flex: 1; background: #F5F7F9; border: 1px solid #E0E8F0;
            padding: 10px 15px; border-radius: 20px; font-size: 12px; color: #999;
        }
        .send-btn { background: #0077CC; width: 35px; height: 35px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 18px; }
    </style>
</head>
<body>

    <div class="app-window">
        <div class="header">
            <h1>AquaAssist</h1>
            <p>Official NAWASA AI Assistant</p>
            <div class="status-pill">● OFFICE OPEN</div>
            <div class="wave"></div>
        </div>

        <div class="chat-area">
            <div class="msg bot">👋 Welcome! I'm AquaAssist. I can help you report leaks, check your bill, or find office locations in Grenada.</div>
            <div class="msg user">I'd like to report a leak in St. George's.</div>
            <div class="msg bot">I can help with that! Please upload a photo if you have one, or describe exactly where the leak is located.</div>
        </div>

        <div class="quick-actions">
            <div class="qa-btn">👷 Report Leak</div>
            <div class="qa-btn">🚰 Outage Map</div>
            <div class="qa-btn">💳 Pay Bill</div>
            <div class="qa-btn">📍 Locations</div>
        </div>

        <div class="input-bar">
            <div class="input-field">Ask about your water...</div>
            <div class="send-btn">💧</div>
        </div>
    </div>

</body>
</html>
