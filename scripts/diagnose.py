import os, time
os.environ['DISPLAY'] = ':99'
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

options = Options()
for arg in ['--no-sandbox','--disable-setuid-sandbox','--single-process',
            '--no-zygote','--disable-gpu','--use-gl=swiftshader',
            '--disable-vulkan','--disable-dev-shm-usage','--mute-audio',
            '--window-size=1920,1080','--autoplay-policy=no-user-gesture-required']:
    options.add_argument(arg)
options.add_experimental_option('excludeSwitches', ['enable-automation'])

driver = webdriver.Chrome(
    service=Service('/usr/local/bin/chromedriver', log_path='/tmp/cd.log'),
    options=options
)
driver.get('https://www.youtube.com/watch?v=mPXA2P1x4Xo&autoplay=1')
time.sleep(12)

# Buttons on page
btns = driver.find_elements(By.TAG_NAME, 'button')
print('Total buttons:', len(btns))
for b in btns[:10]:
    label = b.get_attribute('aria-label')
    cls   = (b.get_attribute('class') or '')[:50]
    print('  aria-label=%r  class=%r' % (label, cls))

# Video element state
vids = driver.find_elements(By.TAG_NAME, 'video')
print('Video elements:', len(vids))
if vids:
    js = """
var v = document.querySelector('video');
return {
  readyState: v.readyState,
  paused:     v.paused,
  src:        v.src.substring(0,80),
  duration:   v.duration,
  currentTime: v.currentTime,
  networkState: v.networkState
};
"""
    info = driver.execute_script(js)
    for k, v in info.items():
        print(' ', k, '=', v)

print('Page title:', driver.title)
driver.quit()
