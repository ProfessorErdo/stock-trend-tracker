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



def load_stock_codes(price_date='20251219'): 
    stocks = pd.read_csv(f'../data/processed/stock-valuation/stocks_values_filtered_{price_date}.csv')
    number_of_stocks = len(stocks)
    stock_codes = stocks.code.tolist()
    return number_of_stocks, stock_codes
    

# def send_mail(receiver='', mail_title='', mail_content=''):
#     # ssl login
#     smtp = SMTP_SSL(host_server)
#     # set_debuglevel() for debug, 1 enable debug, 0 for disable
#     # smtp.set_debuglevel(1)
#     smtp.ehlo(host_server)
#     smtp.login(sender_mail, sender_passcode)

#     # construct message
#     msg = MIMEText(mail_content, "plain", 'utf-8')
#     msg["Subject"] = Header(mail_title, 'utf-8')
#     msg["From"] = sender_mail
#     msg["To"] = receiver
#     smtp.sendmail(sender_mail, receiver, msg.as_string())
#     smtp.quit()

def send_mail(receiver='', mail_title='', mail_content='', img_dir='../img/20251219'):
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
    parser.add_argument('--price_date', type=str, default='20251219', help='Price date')
    args = parser.parse_args()
    
    load_dotenv()
    today = datetime.now().strftime('%Y%m%d')
    price_date = args.price_date

    # qq mail sending server
    host_server = os.getenv("SMTP_SERVER")
    sender_mail = os.getenv("SENDER_EMAIL")
    sender_passcode = os.getenv("EMAIL_AUTH_CODE")

    # receiver mail
    receiver = os.getenv("RECEIVER_EMAIL")
    # mail title
    mail_title = f'Stock Analytics Results by {price_date}'
    # load the results
    number_of_stocks, stock_codes = load_stock_codes(price_date=args.price_date)
    # mail contents
    mail_content = f'The analysis results by {price_date} are: \n' + \
    f'There are {number_of_stocks} stocks in total and \n' + \
    f'The stock codes are: {stock_codes}.'

    send_mail(receiver=receiver,mail_title=mail_title,mail_content=mail_content, img_dir=f'../img/{price_date}')
    print('Email sent successfully.')