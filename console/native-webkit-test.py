"""Opt-in WebKitGTK integration probe. SYNTHETIC bridge only, invoked by pytest.

No downloads, browser fallback, production daemon or model calls. Emits boolean/geometry
results only; URI-bearing engine diagnostics are suppressed. Not a hardware acceptance verdict.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('native_probe_host', Path(__file__).with_name('native_window.py'))
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)

LOOKS = [(1920, 1080), (1440, 900), (1024, 768), (800, 600), (390, 844), (320, 480)]
SNAPSHOT = r"""(() => {
 const f=document.getElementById('console'), w=f && f.contentWindow, d=w && w.document;
 if(!d || !w.ElariaShell || !w.ElariaShell.state.daemon) return null;
 const rect=s=>d.querySelector(s).getBoundingClientRect();
 const chat=rect('.term'), orb=rect('.orb'), stage=rect('#stage'), footer=rect('.console-footer');
 const canvas=d.querySelector('#stage canvas'), lamps=rect('.lamps'), input=rect('#input');
 return JSON.stringify({width:innerWidth,height:innerHeight,paired:true,
  overflow:document.documentElement.scrollWidth>innerWidth || document.documentElement.scrollHeight>innerHeight,
  chat:chat.width,orb:orb.width,stage:stage.height,orbHeight:orb.height,
  canvas:!!canvas && canvas.width>0 && canvas.height>0,
  footer:Math.abs(footer.bottom-innerHeight)<2,
  honest:d.querySelector('.console-footer').textContent.includes('not measured audio') &&
         d.querySelector('.console-footer').textContent.includes('no speech'),
  input:input.width>0 && input.right<=chat.right+1,
  lamps:lamps.left>=0 && lamps.right<=innerWidth,
  reply:d.getElementById('logpad').textContent.includes('Synthetic wire reply'),
  receipt:!!d.querySelector('.attribution')});
})()"""


def main():
    result_fd = os.dup(1)
    host.silence_runtime_output()
    from gi.repository import GLib

    Gtk, WebKit = host.load_runtime()
    if not Gtk.init_check(None)[0]:
        return 2
    pairing = host.read_launch_file(Path(sys.argv[1]))
    window, view = host.build_window(Gtk, WebKit, pairing, LOOKS[0])
    rows, state = [], {'busy': False, 'done': False, 'index': 0, 'sent': False, 'cross': None}

    def finish(passed):
        if state['done']:
            return
        state['done'] = True
        os.write(result_fd, json.dumps({'passed': passed, 'looks': rows,
                                       'cross_origin_denied': state['cross'] is True,
                                       'title': window.get_title() == 'ELARIA'}).encode() + b'\n')
        Gtk.main_quit()

    def evaluate(target, script, callback):
        def complete(widget, task, _data):
            try:
                value = widget.evaluate_javascript_finish(task)
                callback(None if value.is_null() or value.is_undefined() else value.to_string())
            except Exception:
                finish(False)
        target.evaluate_javascript(script, -1, None, None, None, complete, None)

    # Separate, ephemeral UNTRUSTED document tests WebKit's actual Origin/CORS behavior.
    # It is intentionally not the production view (whose navigation policy forbids it).
    foreign = WebKit.WebView.new_with_context(WebKit.WebContext.new_ephemeral())
    origin = pairing.split('/#')[0]
    token = pairing.split('#pair=')[1]
    attack = '''window.probe={{}};
const socket=new WebSocket({});
socket.onopen=()=>{{window.probe.ws=false;socket.close()}};
socket.onerror=()=>{{window.probe.ws=true}};
fetch({}).then(()=>{{window.probe.http=false}}).catch(()=>{{window.probe.http=true}});
'''.format(json.dumps(origin.replace('http:', 'ws:') + '/elaria?token=' + token),
       json.dumps(origin + '/console?token=' + token))
    foreign.load_html('<!doctype html><script>' + attack + '</script>', origin.replace('127.0.0.1', 'localhost') + '/')

    def tick():
        if state['done']:
            return False
        if state['busy']:
            return True
        state['busy'] = True

        def snapshot(value):
            state['busy'] = False
            if not value:
                return
            row = json.loads(value)
            width, height = LOOKS[state['index']]
            if (row['width'], row['height']) != (width, height):
                return  # WM/layout may still be resizing; the overall deadline fails if clamped
            valid = (not row['overflow'] and row['chat'] > width * .35 and row['footer']
                     and row['honest'] and row['input'] and row['lamps'])
            if width > 680:
                valid = valid and row['canvas']
            if width > 1040:
                valid = valid and abs(row['orb'] / width - .36) < .003
                valid = valid and abs(row['stage'] / row['orbHeight'] - .80) < .006
            if not valid:
                finish(False)
                return
            if state['index'] < len(LOOKS) - 1:
                rows.append(row)
                state['index'] += 1
                window.resize(*LOOKS[state['index']])
                return
            if not state['sent']:
                state['sent'] = True
                evaluate(view, """(() => { const w=document.getElementById('console').contentWindow;
 const d=w.document; d.getElementById('input').value='synthetic native transport test';
 d.getElementById('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true})); })()""",
                         lambda _value: None)
            elif row['reply'] and row['receipt']:
                def cross(value):
                    if value:
                        flags = json.loads(value)
                        if 'ws' in flags and 'http' in flags:
                            state['cross'] = flags['ws'] is True and flags['http'] is True
                            rows.append(row)
                            finish(state['cross'] and window.get_title() == 'ELARIA')
                evaluate(foreign, 'JSON.stringify(window.probe || {})', cross)
        evaluate(view, SNAPSHOT, snapshot)
        return True

    GLib.timeout_add(200, tick)
    GLib.timeout_add_seconds(60, lambda: (finish(False), False)[1])
    Gtk.main()
    os.close(result_fd)
    return 0 if state['done'] else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        sys.exit(2)  # no diagnostic may serialize a pairing URI
