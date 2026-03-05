"""
Flask Web 应用入口
运行: python app.py
访问: http://localhost:5000/login
"""

import os

from flask import Flask, redirect, send_from_directory, url_for

from auth.models import init_db, seed_demo_user
from auth.routes import bp as auth_bp

app = Flask(__name__, static_folder="static", template_folder="templates")
app.register_blueprint(auth_bp)


@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


@app.route("/login")
def login_page():
    return send_from_directory("templates", "login.html")


# 捕获未认证跳转
@app.errorhandler(401)
def unauthorized(e):
    return redirect(url_for("login_page"))


if __name__ == "__main__":
    init_db()
    seed_demo_user()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=os.environ.get("FLASK_ENV") != "production", port=port)
