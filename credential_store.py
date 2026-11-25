"""Windows DPAPI current-user credential storage; no plaintext tokens on disk."""
import os, ctypes, subprocess
from pathlib import Path
from ctypes import wintypes

def location():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'VocabResearch' / 'github_token.dpapi'

class BLOB(ctypes.Structure):
    _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]

def transform(data,encrypt):
    if os.name!='nt':raise RuntimeError('此裝置不支援 Windows DPAPI；請僅使用本次連線。')
    crypt=ctypes.WinDLL('crypt32',use_last_error=True); kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    buf=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
    src=BLOB(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte))); dst=BLOB()
    pblob=ctypes.POINTER(BLOB)
    crypt.CryptProtectData.argtypes=[pblob,wintypes.LPCWSTR,pblob,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,pblob]
    crypt.CryptUnprotectData.argtypes=[pblob,ctypes.c_void_p,pblob,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,pblob]
    kernel.LocalFree.argtypes=[ctypes.c_void_p]; kernel.LocalFree.restype=ctypes.c_void_p
    fn=crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    if not fn(ctypes.byref(src),None,None,None,None,1,ctypes.byref(dst)):raise RuntimeError('Windows 憑證加解密失敗。')
    try:return ctypes.string_at(dst.pbData,dst.cbData)
    finally:kernel.LocalFree(ctypes.cast(dst.pbData,ctypes.c_void_p))

def save(token):
    p=location();p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_bytes(transform(token.encode('utf-8'),True));tmp.replace(p)

def load():
    p=location()
    if os.name!='nt' or not p.exists():return ''
    return transform(p.read_bytes(),False).decode('utf-8')

def clear():
    p=location()
    if p.exists():p.unlink()


def load_github_login():
    """Ask Git Credential Manager for the existing login for the published repository."""
    query='protocol=https\nhost=github.com\npath=yl164202-byte/VocabResearch.git\n\n'
    env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'Never'}
    try:
        result=subprocess.run(['git','-c','credential.interactive=never','credential','fill'],
                              input=query,capture_output=True,text=True,env=env,timeout=10)
    except (OSError,subprocess.TimeoutExpired):
        return ''
    if result.returncode:
        return ''
    return next((line.partition('=')[2] for line in result.stdout.splitlines()
                 if line.startswith('password=')), '')
