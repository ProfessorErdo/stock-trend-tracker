from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.header import Header
from smtplib import SMTP_SSL
from datetime import datetime

import pandas as pd

import os
from dotenv import load_dotenv
import argparse


def load_stock_codes():
    """
    Load stock codes from the filtered stocks file (uses today's date)
    """
    today = datetime.now().strftime('%Y%m%d')
    stocks = pd.read_csv(f'../data/processed/stock-valuation/stocks_values_filtered_{today}.csv')
    number_of_stocks = len(stocks)
    stock_codes = stocks.code.tolist()
    return number_of_stocks, stock_codes


def send_mail(receiver='', mail_title='', mail_content='', img_dir='../img/'):
    smtp = SMTP_SSL(host_server)
    smtp.ehlo(host_server)
    smtp.login(sender_mail, sender_passcode)

    # Root message
    msg_root = MIMEMultipart('related')
    msg_root['Subject'] = Header(mail_title, 'utf-8')
    msg_root['From'] = sender_mail
    msg_root['To'] = receiver

    # Alternative (HTML)
    msg_alt = MIMEMultipart('alternative')
    msg_root.attach(msg_alt)

    # Build HTML body
    html = f"""
    <html>
      <body>
        <p>{mail_content}</p>
    """

    # Attach images
    for i, filename in enumerate(os.listdir(img_dir)):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            cid = f"img{i}"
            html += f'<p><img src="cid:{cid}" style="max-width:600px;"></p>'

            with open(os.path.join(img_dir, filename), 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', f'<{cid}>')
                img.add_header('Content-Disposition', 'inline', filename=filename)
                msg_root.attach(img)

    html += """
      </body>
    </html>
    """

    msg_alt.attach(MIMEText(html, 'html', 'utf-8'))

    smtp.sendmail(sender_mail, receiver, msg_root.as_string())
    smtp.quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=str, default=None, 
                        help='Date for image folder (default: today)')
    args = parser.parse_args()

    load_dotenv()
    
    today = datetime.now().strftime('%Y%m%d')
    date = args.date if args.date else today

    # qq mail sending server
    host_server = os.getenv("SMTP_SERVER")
    sender_mail = os.getenv("SENDER_EMAIL")
    sender_passcode = os.getenv("EMAIL_AUTH_CODE")

    # receiver mail
    receiver = os.getenv("RECEIVER_EMAIL")
    # mail title
    mail_title = f'Stock Analytics Results by {date}'
    # load the results
    number_of_stocks, stock_codes = load_stock_codes()
    # mail contents
    mail_content = f'The analysis results by {date} are: \n' + \
    f'There are {number_of_stocks} stocks in total and \n' + \
    f'The stock codes are: {stock_codes}.'

    send_mail(receiver=receiver, mail_title=mail_title, mail_content=mail_content, img_dir=f'../img/{date}')
    print('Email sent successfully.')