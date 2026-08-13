import os, time, shutil
os.environ['DISPLAY'] = ':99'
import undetected_chromedriver as uc

uc_driver = '/tmp/chromedriver_uc'
if not os.path.exists(uc_driver):
    shutil.copy2('/usr/local/bin/chromedriver', uc_driver)
    os.chmod(uc_driver, 0o755)

options = uc.ChromeOptions()
for arg in ['--no-sandbox','--disable-setuid-sandbox','--disable-namespace-sandbox',
            '--disable-gpu','--disable-gpu-compositing','--use-gl=swiftshader',
            '--use-angle=swiftshader-webgl','--disable-vulkan','--disable-dev-shm-usage',
            '--autoplay-policy=no-user-gesture-required','--window-size=1920,1080',
            '--disable-infobars','--disable-notifications']:
    options.add_argument(arg)

driver = uc.Chrome(
    options=options,
    driver_executable_path=uc_driver,
    version_main=None,
    headless=True,
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
