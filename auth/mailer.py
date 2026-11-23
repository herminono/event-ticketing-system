import smtplib
import ssl
from email.message import EmailMessage
from flask import current_app

def send_reset_email(recipient,reset_link):
    config = current_app.config
    message = EmailMessage()
    message["Subject"] = "Password reset"
    message["From"] = config["MAIL_FROM"]
    message["To"] = recipient
    message.set_content(
        "Reset your password\n\n"
        "Click this link to reset your password\n"
        f"{reset_link}\n\n"
        "This link will expire in 30 mins."
        "Event Ticketing System"
    )
    context = ssl.create_default_context()
    if config["SMTP_USE_SSL"]:
        with smtplib.SMTP_SSL(
            config["SMTP_HOST"],
            config["SMTP_PORT"],
            timeout=15,
            context=context,
        ) as server:
            server.login(
                config["SMTP_USERNAME"],
                config["SMTP_PASSWORD"],
            )
            server.send_message(message)
    else:
        with smtplib.SMTP(
            config["SMTP_HOST"],
            config["SMTP_PORT"],
            timeout=15,
        ) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(
                config["SMTP_USERNAME"],
                config["SMTP_PASSWORD"],
            )
            server.send_message(message)