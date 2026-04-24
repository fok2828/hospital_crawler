
import time
import io
import threading
import cv2
import ddddocr
import numpy as np
from PIL import Image
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import undetected_chromedriver as uc

from concurrent.futures import ThreadPoolExecutor

# --- 設定 (請根據您的需求修改) ---
BASE_URL = "https://reg.ntuh.gov.tw/WebReg/WebReg/RegShowBlock?vHospCode=T0" #總院
TARGET_DEPT = "精神"  # 要掛號的科別 (請使用網頁上顯示的完整名稱)
TARGET_DOCTOR = "林欣妤"  # 要掛號的醫生 (請使用網頁上顯示的完整名稱)
ID_NUMBER = "A123456789"  # 您的身分證字號
BIRTHDAY = "19840326"  # 您的生日 (格式: YYYYMMDD)

# --- 常數 ---
MAX_REFRESH_ATTEMPTS = 5  # 尋找可掛號日期的最大刷新次數
MAX_SUBMIT_ATTEMPTS = 1   # 提交表單的最大嘗試次數
MAX_WORKERS = 1           # 同時執行掛號任務的線程數

# 初始化 OCR
OCR = ddddocr.DdddOcr(show_ad=False)

def solve_captcha(image_bytes: bytes) -> str:
    try:
        # 儲存驗證碼圖片
        with open("captcha.png", "wb") as f:
            f.write(image_bytes)
        
        # 讀取原始圖片
        np_arr = np.frombuffer(image_bytes, np.uint8)
        origin_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if origin_img is None: 
            return ""
        
        # 定義辨識策略清單
        # 策略 1: 原始圖片 (ddddocr 對原圖通常效果最好)
        # 策略 2: 放大兩倍 (增加像素特徵)
        # 策略 3: 灰階 + 放大
        # 策略 4: 二值化 (你的舊邏輯)
        
        strategies = [
            ("Origin", origin_img),
            ("Resize", cv2.resize(origin_img, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_LINEAR)),
            ("Gray_Resize", cv2.resize(cv2.cvtColor(origin_img, cv2.COLOR_BGR2GRAY), (0, 0), fx=2, fy=2))
        ]
        
        for name, img_proc in strategies:
            _, buffer = cv2.imencode('.png', img_proc)
            processed_bytes = buffer.tobytes()
            
            result = OCR.classification(processed_bytes)
            print(f"[*] 嘗試策略 [{name}]: {result=}")

            # 判斷是否符合條件
            if len(result) == 6:
                return result.upper()
        
        # 如果所有策略都試完還是沒 6 碼，回傳目前最長的或是重新整理網頁
        print("[-] 無法辨識出 6 碼驗證碼")
        return result 
    except Exception as e:
        print(f"[-] 辨識發生異常: {e}")
        return ""

def registration_worker(driver: webdriver.Chrome, thread_num: int=1):
    """
    執行單次掛號流程的 Worker。
    每個 Worker 會在自己的瀏覽器中執行，以實現並發操作。
    """
    try:
        for attempt in range(MAX_SUBMIT_ATTEMPTS):
            print(f"[Thread-{thread_num}] 第 {attempt + 1}/{MAX_SUBMIT_ATTEMPTS} 次嘗試提交...")
            try:
                # 填寫身分證和生日
                driver.find_element(By.ID, 'txtInputID').send_keys(ID_NUMBER)
                driver.find_element(By.ID, 'year').send_keys(BIRTHDAY[:4])
                driver.find_element(By.ID, 'month').send_keys(BIRTHDAY[4:6])
                driver.find_element(By.ID, 'day').send_keys(BIRTHDAY[6:])


                # 處理驗證碼
                captcha_img_xpath = "//form[@id='RegForm']//img"
                captcha_element = driver.find_element(By.XPATH, captcha_img_xpath)
                captcha_url = captcha_element.get_attribute("src")

                print(f"[*] 驗證碼連結: {captcha_url}")
                captcha_code = solve_captcha(captcha_element.screenshot_as_png)
                if captcha_code == "":
                    driver.refresh()
                    continue
                
                print(f"[Thread-{thread_num}][+] 驗證碼辨識結果: {captcha_code}")
                driver.find_element(By.ID, 'validText').send_keys(captcha_code)
                driver.find_element(By.ID, "patientIdentityConfirm").click()
                time.sleep(4)
                
                driver.save_screenshot("after_click.png")

                # 2. 搜尋特定的錯誤關鍵字 (例如：格式錯誤、不符)
                page_text = driver.find_element(By.TAG_NAME, "body").text
                print(page_text)
                # if not captcha_code:
                #     print(f"[Thread-{thread_num}][-] 無法辨識驗證碼，重新整理頁面。")
                #     driver.refresh()
                #     continue

                # print(f"[Thread-{thread_num}][+] 驗證碼辨識結果: {captcha_code}")
                # driver.find_element(By.ID, 'txtVerifyCode').send_keys(captcha_code)
                
                # # 點擊送出
                # driver.find_element(By.ID, 'btnOK').click()

                # # 檢查結果
                # try:
                #     # 等待彈出視窗
                #     alert = WebDriverWait(driver, 2).until(EC.alert_is_present())
                #     alert_text = alert.text
                #     print(f"[Thread-{thread_num}][!] 掛號結果: {alert_text}")
                #     alert.accept()

                #     if "掛號成功" in alert_text:
                #         print(f"[Thread-{thread_num}][SUCCESS] 掛號成功！")
                #         return True
                #     elif "已額滿" in alert_text:
                #         print(f"[Thread-{thread_num}][-] 此時段已額滿，停止此線程。")
                #         return False
                #     # 其他失敗原因 (如驗證碼錯誤)，會繼續重試
                    
                # except TimeoutException:
                #     print(f"[Thread-{thread_num}][-] 未偵測到彈出視窗，可能發生頁面錯誤。")
                
                # # 短暫等待後刷新頁面準備重試
                # time.sleep(0.5)
                # driver.refresh()

            except (NoSuchElementException, TimeoutException) as e:
                print(f"[Thread-{thread_num}][-] 頁面元素載入失敗或超時，重新整理頁面: {e}")
                driver.refresh()
                time.sleep(1)

    except Exception as e:
        print(f"[Thread-{thread_num}][CRITICAL] Worker 發生嚴重錯誤: {e}")
    finally:
        if driver:
            driver.quit()
        print(f"[Thread-{thread_num}] 線程結束。")
    return False


def find_available_slot(driver: webdriver.Chrome) -> str | None:
    """
    在主瀏覽器中尋找可用的掛號連結。
    """
    for attempt in range(MAX_REFRESH_ATTEMPTS):
        try:
            # 找到包含醫生名字的 table row
            # **注意**: 這個 XPath 可能需要根據實際網頁結構修改
            button_xpath = f"//div[contains(@id, '{TARGET_DOCTOR}')]//button[contains(@class, 'avaliable')]"
            WebDriverWait(driver, 1).until(
                EC.presence_of_element_located((By.XPATH, button_xpath))
            )
            target_buttons = driver.find_elements(By.XPATH, button_xpath)

            if target_buttons:
                print(f"[+] 找到 {len(target_buttons)} 筆可掛號的日期，抓取最後一筆。")
                driver.execute_script("arguments[0].click();", target_buttons[-1])
                #registration_url = driver.current_url
                break
            else:
                print(f"[-] 未找到 {TARGET_DOCTOR} 醫生的可掛號時段。 ({attempt + 1}/{MAX_REFRESH_ATTEMPTS})")
                driver.refresh()
                time.sleep(0.2)

        except (NoSuchElementException, TimeoutException):
            print(f"[!] 無法找到 {TARGET_DOCTOR} 醫生的資訊，可能頁面結構已變更或醫生本日無門診。")

def get_driver_options() -> Options:
    """
    設定 Chrome 瀏覽器選項。
    """
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # 1. 消除「自動化測試」提示列
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    # 2. 隱藏自動化特徵，避免被網站封鎖渲染
    options.add_argument("--disable-blink-features=AutomationControlled")
    # 3. 隱藏自動化特徵，強制設定一個常見的解析度。
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-maximized")
    # 4. 隱藏自動化特徵，嘗試關閉 GPU
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")

    return options


def main():
    """
    主程序，負責導航、尋找醫生並啟動多線程掛號 Worker。
    """
    driver = None
    try:
        #with uc.Chrome(options=uc.ChromeOptions(), version_main=147) as driver:
        with webdriver.Chrome(options=get_driver_options()) as driver:
            # 3. 前往目標網站
            driver.get(BASE_URL)

            # 1. 點擊科別
            print(f"[*] 正在尋找科別: {TARGET_DEPT}")
            # **注意**: 這個 LINK_TEXT 需要與網頁上的完全一致
            dept_link = WebDriverWait(driver, 0.1).until(
                EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, TARGET_DEPT))
            )
            dept_link.click()
            print(f"[+] 已進入 {TARGET_DEPT} 頁面")

            # 2. 尋找可掛號的連結
            find_available_slot(driver)

            # 3. 啟動掛號 Worker
            registration_worker(driver)
    finally:
        # 主瀏覽器完成任務後即可關閉
        if driver:
            driver.quit()
    

if __name__ == "__main__":
    main()