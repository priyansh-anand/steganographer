from cryptography.fernet import Fernet
import base64
import hashlib

def encryptData(data: bytes, key: str) -> bytes:
    key = base64.urlsafe_b64encode(hashlib.md5(key.encode()).hexdigest().encode())

    f = Fernet(key)
    encData = f.encrypt(data)
    return encData

def decryptData(data: bytes, key: str) -> bytes:
    try:
        key = base64.urlsafe_b64encode(hashlib.md5(key.encode()).hexdigest().encode())

        f = Fernet(key)
        decData = f.decrypt(data)
        return decData
    except:
        print("[!] Invalid password or data")
        exit()
