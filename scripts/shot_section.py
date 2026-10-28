"""定点截图：把长报告里的某个区块干净地截出来（两趟式，零时序依赖）。

第一趟：注入探针，dump-dom 读出目标锚点的文档 Y。
第二趟：把 body{margin-top:-Ypx} 写进静态 <style>，再截图。

为什么不用「load 里设 style.marginTop」：那会与截图时机竞争，常静默失效，
表现为截到页面顶部，且不报任何错。

用法:
  python shot_section.py <html> <css选择器> <输出png> [宽=1440] [高=1100] [偏移px=0] [查询串]

  <html>      可以是绝对路径或相对路径
  [偏移px]    正数 = 向上多看一点；负数 = 向下跳过一点
  [查询串]    如 theme=dark，会拼到 file:// URL 后面

注意:
  - 两趟的 --window-size 必须一致，否则布局宽度不同会让 Y 错位（截到不相干区块）。
  - Chrome headless 最小窗口宽为 500px，传更小值仍按 500 渲染（图会被裁，不是页面溢出）。
"""
import os
import re
import subprocess
import sys

CHROME = os.environ.get('SHOT_CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
TMP_DIR = os.environ.get('SHOT_TMP', 'tmp_shot')

if len(sys.argv) < 4:
    print(__doc__)
    sys.exit(1)

SRC = os.path.abspath(sys.argv[1])
SEL = sys.argv[2]
OUT = os.path.abspath(sys.argv[3])
W = int(sys.argv[4]) if len(sys.argv) > 4 else 1440
H = int(sys.argv[5]) if len(sys.argv) > 5 else 1100
EXTRA = int(sys.argv[6]) if len(sys.argv) > 6 else 0
QUERY = sys.argv[7] if len(sys.argv) > 7 else ''

html = open(SRC, encoding='utf-8').read()
if '</body>' not in html:
    print('FAIL 模板缺少 </body>')
    sys.exit(1)

os.makedirs(TMP_DIR, exist_ok=True)

# 关掉入场动画与过渡：保证截图不抓在中途态。
# 这是 --force-prefers-reduced-motion 之外的双保险（该 flag 只在模板写了对应媒体查询时才有效）。
QUIET = ('<style id="__quiet">'
         '.rv,.reveal{opacity:1!important;transform:none!important;'
         'transition:none!important;animation:none!important}'
         '.bar .fi{transition:none!important}'
         '*{animation:none!important;transition:none!important}'
         'html{scroll-behavior:auto!important}</style>')


def url_of(path):
    u = 'file:///' + path.replace('\\', '/').replace(' ', '%20')
    return u + (('?' + QUERY) if QUERY else '')


def run(args):
    return subprocess.run(args, capture_output=True)


# ---------- 第一趟：探针（窗口尺寸必须与第二趟相同） ----------
probe_html = html.replace('</body>', QUIET + '''
<script>
addEventListener('load',function(){
  var e=document.querySelector(%s);
  document.title='SHOTY='+(e?Math.round(e.getBoundingClientRect().top+window.scrollY):'-1');
});
</script>
</body>''' % repr(SEL))
probe_path = os.path.abspath(os.path.join(TMP_DIR, '_shot_probe.html'))
open(probe_path, 'w', encoding='utf-8').write(probe_html)

r = run([CHROME, '--headless=new', '--disable-gpu', '--no-sandbox',
         '--hide-scrollbars', '--force-device-scale-factor=1',
         '--virtual-time-budget=9000',
         '--window-size=%d,%d' % (W, H),
         '--dump-dom', url_of(probe_path)])
dom = r.stdout.decode('utf-8', 'replace')
m = re.search(r'SHOTY=(-?\d+)', dom)
if not m:
    print('FAIL 探针未返回偏移（选择器 %s 未命中？）' % SEL)
    sys.exit(1)
raw_y = int(m.group(1))
if raw_y < 0:
    print('FAIL 选择器 %s 在 DOM 中不存在' % SEL)
    sys.exit(1)
y = max(0, raw_y + EXTRA)

# ---------- 第二趟：静态位移 + 截图 ----------
shot_html = html.replace('</body>',
                         QUIET + '<style id="__shift">body{margin-top:-%dpx !important}</style>'
                         % y + '</body>')
shot_path = os.path.abspath(os.path.join(TMP_DIR, '_shot_tmp.html'))
open(shot_path, 'w', encoding='utf-8').write(shot_html)

run([CHROME, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--hide-scrollbars', '--force-device-scale-factor=1',
     '--virtual-time-budget=9000',
     '--window-size=%d,%d' % (W, H),
     '--screenshot=' + OUT, url_of(shot_path)])

if os.path.exists(OUT):
    print('OK %-30s Y=%-7d %6.0f KB' % (os.path.basename(OUT), y, os.path.getsize(OUT) / 1024))
else:
    print('FAIL 截图未生成')
    sys.exit(1)
