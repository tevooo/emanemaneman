import json
import urllib.request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, CallbackQueryHandler, Application, CallbackContext
import re
from unidecode import unidecode
import os
import asyncio
import datetime
import logging

# Logging configuration
logging.basicConfig(
    filename='bot_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
BASE_URL = "https://edesis.api.edesis.com"
login_url = f"{BASE_URL}/api/TokenAuth/Authenticate"
data_url = f"{BASE_URL}/api/services/app/Denemes/GetAll?Filter=&DenemeAdiFilter=&BKitapcihiVarmiFilter=-1&DenemeKesildimi=-1&DonemId=-1&SinavTuruId=-1&DenemeSetiId=-1&YayineviId=0&Hazirlayan=0&DenemeSetiDenemeSetiAdiFilter=&SinavTuruNameFilter=&DonemDonemAdiFilter=&md5Key=&md10Key=&Sorting=denemeSetiAdi&SkipCount=0&MaxResultCount=100000"
download_url = f"{BASE_URL}/api/services/app/Denemes/GetDenemeCevapAnahtariPdf"

TOKEN = '7924307739:AAEV3N2R2tyPlLHavNViHGXtzDIZfMzk70Y'
headers = {"Content-Type": "application/json"}

# Global variables
token = None
full_data = []
filtered_data = []
user_downloads = {}
DAILY_LIMIT = 10
last_login_time = None
TOKEN_FILE = "token.txt"

# Token dosyasını oku veya login yap
def load_token():
    global token, last_login_time
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            token = f.read().strip()
            last_login_time = datetime.datetime.now()
            print(f"Token loaded from file: {token[:10]}...")
    else:
        print("Token file not found, will acquire new token on first login.")

def save_token(new_token):
    with open(TOKEN_FILE, 'w') as f:
        f.write(new_token)
    print(f"New token saved to {TOKEN_FILE}: {new_token[:10]}...")

def check_download_limit(user_id):
    today = datetime.datetime.now().date()
    
    if user_id not in user_downloads or user_downloads[user_id]['date'] != today:
        user_downloads[user_id] = {
            'date': today,
            'count': 0
        }
    
    if user_downloads[user_id]['count'] >= DAILY_LIMIT:
        return False
    
    return True

def increment_download_count(user_id):
    today = datetime.datetime.now().date()
    
    if user_id not in user_downloads or user_downloads[user_id]['date'] != today:
        user_downloads[user_id] = {
            'date': today,
            'count': 0
        }
    
    user_downloads[user_id]['count'] += 1

def normalize_text(text):
    if text:
        fixed_text = unidecode(text)
        normalized = fixed_text.upper().strip()
        return normalized
    return ""

def filter_data(data, sınav=None, tür=None, dönem=None):
    filtered = []
    items = data.get("result", {}).get("items", [])

    for item in items:
        deneme = item.get("deneme", {})

        if sınav:
            normalized_sınav = normalize_text(sınav)
            denemeAdi = normalize_text(deneme.get("denemeAdi", ""))
            if normalized_sınav not in denemeAdi:
                continue

        if tür:
            normalized_tür = normalize_text(tür)
            sinavTuruName = normalize_text(item.get("sinavTuruName", ""))
            if normalized_tür not in sinavTuruName:
                continue

        if dönem:
            normalized_dönem = normalize_text(dönem)
            donemDonemAdi = normalize_text(item.get("donemDonemAdi", ""))
            if normalized_dönem not in donemDonemAdi:
                continue

        filtered.append({
            "id": deneme.get("id"),
            "denemeAdi": deneme.get("denemeAdi"),
            "sinavTuruName": item.get("sinavTuruName"),
            "donemDonemAdi": item.get("donemDonemAdi")
        })

    filtered.sort(key=lambda x: x['denemeAdi'].lower())
    return filtered

async def login():
    global token, last_login_time
    login_payload = {
        "tenancyName": "edesis",
        "userNameOrEmailAddress": "edesis",
        "password": "edesis"
    }
    try:
        data = json.dumps(login_payload).encode('utf-8')
        req = urllib.request.Request(login_url, data=data, headers=headers, method='POST')
        with urllib.request.urlopen(req) as response:
            response_data = json.load(response)
            if response.status == 200 and response_data.get("success"):
                token = response_data["result"]["accessToken"]
                last_login_time = datetime.datetime.now()
                save_token(token)
                print(f"New token acquired: {token[:10]}...")
                return token
            else:
                print("Login failed:", response_data.get("error", "Unknown error"))
                return None
    except Exception as e:
        print("Login error:", str(e))
        return None

async def fetch_data():
    global token
    try:
        if not token:
            print("Token not available, attempting login...")
            token = await login()
            if not token:
                return None
        
        auth_headers = headers.copy()
        auth_headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(data_url, headers=auth_headers)
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                return json.load(response)
            else:
                print(f"Unexpected status code: {response.status}")
                return None
    except urllib.error.HTTPError as e:
        if e.code == 401:  # Token geçersiz
            print("Token invalid (401), forcing re-login...")
            token = await login()
            if token:
                return await fetch_data()  # Yeni token ile tekrar dene
            else:
                print("Re-login failed.")
                return None
        else:
            print(f"HTTP Error: {e}")
            return None
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

async def update_data():
    global token, full_data, last_login_time
    print("Checking data update...")

    current_time = datetime.datetime.now()
    time_diff = (current_time - last_login_time).total_seconds() if last_login_time else float('inf')
    print(f"Time since last token refresh: {time_diff:.2f} seconds")
    
    if not last_login_time or time_diff >= 21600:  # 6 saat = 21600 saniye
        print("6 hours passed, refreshing token...")
        token = await login()
        if not token:
            print("Token refresh failed, retrying in 1 hour.")
            await asyncio.sleep(3600)
            await update_data()
            return

    # Veriyi güncelle
    data = await fetch_data()
    if data:
        full_data = data
        try:
            with open('deneme_verisi.json', 'w', encoding='utf-8') as f:
                json.dump(full_data, f, ensure_ascii=False, indent=4)
                print("Full data saved successfully to 'deneme_verisi.json'.")
        except Exception as e:
            print(f"Error saving data to file: {e}")
    else:
        print("Data fetch failed, retrying in 1 hour...")
        await asyncio.sleep(3600)

    # 1 saat sonra tekrar kontrol et
    print("Waiting 1 hour for next check...")
    await asyncio.sleep(3600)
    await update_data()

async def start(update: Update, context: CallbackContext):
    user = update.message.from_user
    user_mention = f"@{user.username}" if user.username else f"{user.first_name}"
    user_id = user.id

    await update.message.reply_text(
        f"Merhabalar, {user_mention} ({user_id}) kullanıcı, bu bot @kcypdf tarafından oluşturulmuştur. "
        "Botu verimli kullanabilmek için /aciklama kısmını okuyunuz. "
        "\n\nÖrnek kullanım şu şekilleri;\n\n/cevap -sınav ÖZDEBİR -tür TYT -dönem 2024-2025\n/cevap -sınav bilgi sarmal -tür ayt -dönem 2023-2024 \n-sınav -tür -dönem yazarak kullanmanız zorunludur. Aksi taktirde sonuç alamazsınız."
    )

async def aciklama(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "Kullanım mantığı oldukça basit:\n\nEN ÖNEMLİ KISIM -sınav -tür -dönem KULLANMANIZ KULLANMAZSANIZ YANIT ALAMAZSINIZ!!!"
        "-sınav kısmına yayın evini yazıyorsunuz.\n(Bilgi sarmal, Kafa dengi, Yıldızlar ligi,şeklinde olan yayın evlerini ayrı yazınız -sınav bilgi sarmal -sınav kafa dengi şeklinde.)\n\nÖrneğin;\n-sınav 3D\n-sınav BİLGİ SARMALI\n-sınav BİREY şeklinde.\n"
        "-tür kısmına TYT, AYT, YDT, LGS... girmeniz gerekmekte.\n-dönem ise 2018-2019, 2019-2020, ... 2024-2025 gibi formatta girilmelidir.\n\n"
        "Çıkan sonuca bir defa basmanız yeterlidir.\n\n"
        "En son oluşacak yanıt şu şekilde olmalıdır,\n/cevap -sınav ÖZDEBİR -tür TYT -dönem 2024-2025\n\n"
        f"Günlük indirme limitiniz: {DAILY_LIMIT} dosya"
    )

async def cevap(update: Update, context: CallbackContext):
    command = update.message.text
    print(f"Alınan komut: {command}")

    match = re.match(r"/cevap -sınav ([^\-]+) -tür ([^\-]+) -dönem (.+)$", command)
    if not match:
        await update.message.reply_text("Geçersiz format. Lütfen şu formatı kullanın: \n /cevap -sınav Özdebir -tür TYT -dönem 2024-2025")
        print("Geçersiz format girildi.")
        return

    sınav = match.group(1)
    tür = match.group(2)
    dönem = match.group(3)

    print(f"Sınav: {sınav}, Tür: {tür}, Dönem: {dönem}")

    global filtered_data
    filtered_data = filter_data(full_data, sınav, tür, dönem)
    print(f"Filtrelenmiş veri sayısı: {len(filtered_data)}")

    if not filtered_data:
        await update.message.reply_text("Belirttiğiniz kriterlere uygun sonuç bulunamadı.")
        print("Filtreleme sonuç vermedi.")
        return

    context.user_data['filtered_data'] = filtered_data
    context.user_data['page'] = 0
    await send_results(update, context)

async def send_results(update: Update, context: CallbackContext):
    filtered_data = context.user_data.get('filtered_data', [])
    page = context.user_data.get('page', 0)

    PAGE_SIZE = 10
    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    data_to_show = filtered_data[start_idx:end_idx]

    logger.info(f"Page: {page}, Items shown: {len(data_to_show)}")

    buttons = []
    for item in data_to_show:
        callback_data = str(item['id'])
        buttons.append([InlineKeyboardButton(item["denemeAdi"], callback_data=callback_data)])

    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(InlineKeyboardButton("◀ Önceki", callback_data="prev"))
    if end_idx < len(filtered_data):
        pagination_buttons.append(InlineKeyboardButton("Sonraki ▶", callback_data="next"))

    reply_markup = InlineKeyboardMarkup(buttons + [pagination_buttons])

    if update.callback_query:
        await update.callback_query.message.edit_text("Lütfen bir sınav seçiniz:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Lütfen bir sınav seçiniz:", reply_markup=reply_markup)

async def pagination(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    logger.info(f"Callback data: {query.data}")

    user_id = query.from_user.id

    if query.data == "prev":
        context.user_data['page'] -= 1
        logger.info(f"Previous page. New page: {context.user_data['page']}")
    elif query.data == "next":
        context.user_data['page'] += 1
        logger.info(f"Next page. New page: {context.user_data['page']}")
    else:
        if not check_download_limit(user_id):
            remaining_time = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
            time_diff = remaining_time - datetime.datetime.now()
            hours, remainder = divmod(time_diff.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            await query.message.reply_text(
                f"Günlük indirme limitiniz dolmuştur ({DAILY_LIMIT}/{DAILY_LIMIT}).\n"
                f"Yeni indirme hakkı için kalan süre: {hours} saat {minutes} dakika"
            )
            return

        deneme_id = query.data
        selected_exam = next((item for item in context.user_data['filtered_data'] if str(item['id']) == deneme_id), None)
        if selected_exam:
            deneme_adı = selected_exam.get("denemeAdi", "Bilinmeyen Deneme")
            dönem = selected_exam.get("donemDonemAdi", "Bilinmeyen Dönem")
            logger.info(f"Selected exam ID: {deneme_id}, Deneme: {deneme_adı}, Dönem: {dönem}")
        else:
            await query.message.reply_text("Seçilen sınav bulunamadı.")
            logger.error(f"No exam found with ID: {deneme_id}")
            return

        await query.message.delete()

        file_path = await download_answer_key_v2(deneme_id)
        if file_path:
            increment_download_count(user_id)
            remaining_downloads = DAILY_LIMIT - user_downloads[user_id]['count']
            
            file_name = f"{dönem} - {deneme_adı}.pdf"
            caption = f"@kcyca_bot ({dönem}) {deneme_adı} \npdf: @kcypdf\n\nKalan indirme hakkı: {remaining_downloads}/{DAILY_LIMIT}"
            
            await query.message.reply_document(
                document=open(file_path, 'rb'),
                filename=file_name,
                caption=caption
            )
            print(f"Dosya indirildi: {file_path}")

            os.remove(file_path)
            print(f"Dosya silindi: {file_path}")

            alert_message = await query.message.reply_text("Dosyanız başarıyla indirildi.")
            await asyncio.sleep(10)
            await alert_message.delete()
        else:
            await query.message.reply_text("Cevap anahtarı indirilemedi. Lütfen tekrar deneyin.")
            print("Cevap anahtarı indirilemedi.")
        return

    await send_results(update, context)

async def download_answer_key_v2(deneme_id):
    global token
    try:
        if not token:
            print("Token not available, attempting login...")
            token = await login()
            if not token:
                return None
        
        auth_headers = headers.copy()
        auth_headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{download_url}?id={deneme_id}", headers=auth_headers)
        with urllib.request.urlopen(req) as response:
            response_data = json.load(response)
            if response_data.get("success") and response_data["result"]:
                file_token_url = response_data["result"].get("fileToken")
                if file_token_url:
                    pdf_response = urllib.request.urlopen(file_token_url)
                    file_name = f"cevap_anahtari_{deneme_id}.pdf"
                    with open(file_name, "wb") as file:
                        file.write(pdf_response.read())
                    print(f"PDF dosyası kaydedildi: {file_name}")
                    return file_name
                else:
                    print("fileToken URL bulunamadı.")
                    return None
            else:
                print("API başarılı sonuç döndürmedi.")
                return None
    except urllib.error.HTTPError as e:
        if e.code == 401:  # Token geçersiz
            print("Token invalid (401), forcing re-login...")
            token = await login()
            if token:
                return await download_answer_key_v2(deneme_id)  # Yeni token ile tekrar dene
            else:
                print("Re-login failed.")
                return None
        else:
            print(f"HTTP Error: {e}")
            return None
    except Exception as e:
        print(f"Hata oluştu: {e}")
        return None

async def error_handler(update: Update, context: CallbackContext):
    error = context.error
    logger.error(f"Error occurred: {error}", exc_info=True)

    if update and update.message:
        await update.message.reply_text("Bir hata oluştu. Lütfen daha sonra tekrar deneyin.")
    elif update and update.callback_query:
        await update.callback_query.message.reply_text("Bir hata oluştu. Lütfen daha sonra tekrar deneyin.")

def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("aciklama", aciklama))
    application.add_handler(CommandHandler("cevap", cevap))
    application.add_handler(CallbackQueryHandler(pagination))
    application.add_error_handler(error_handler)

    loop = asyncio.get_event_loop()
    global token, last_login_time
    load_token()  # Token’ı dosyadan yükle
    if not token:
        token = loop.run_until_complete(login())  # Dosyada yoksa login yap
    if token:
        data = loop.run_until_complete(fetch_data())
        if data:
            global full_data
            full_data = data
            try:
                with open('deneme_verisi.json', 'w', encoding='utf-8') as f:
                    json.dump(full_data, f, ensure_ascii=False, indent=4)
                    print("Full data saved successfully to 'deneme_verisi.json'.")
            except Exception as e:
                print(f"Error saving data to file: {e}")

            loop.create_task(update_data())  # update_data fonksiyonunu başlat
            application.run_polling()

if __name__ == "__main__":
    main()
