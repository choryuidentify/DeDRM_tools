#!/usr/bin/env python

"""
Retrieve Adobe ADEPT user key.
"""

from __future__ import with_statement

__license__ = 'GPL v3'

import sys
import os
import struct
from calibre.constants import iswindows, isosx

class ADEPTError(Exception):
    pass

if iswindows:
    from ctypes import windll, c_char_p, c_wchar_p, c_uint, POINTER, byref, \
        create_unicode_buffer, create_string_buffer, CFUNCTYPE, addressof, \
        string_at, Structure, c_void_p, cast, c_size_t, memmove
    from ctypes.wintypes import LPVOID, DWORD, BOOL
    import _winreg as winreg
    
    try:
        from Crypto.Cipher import AES as _aes
    except ImportError:
        _aes = None
    
    DEVICE_KEY_PATH = r'Software\Adobe\Adept\Device'
    PRIVATE_LICENCE_KEY_PATH = r'Software\Adobe\Adept\Activation'
    
    MAX_PATH = 255
    
    kernel32 = windll.kernel32
    advapi32 = windll.advapi32
    crypt32 = windll.crypt32
    
    def GetSystemDirectory():
        GetSystemDirectoryW = kernel32.GetSystemDirectoryW
        GetSystemDirectoryW.argtypes = [c_wchar_p, c_uint]
        GetSystemDirectoryW.restype = c_uint
        def GetSystemDirectory():
            buffer = create_unicode_buffer(MAX_PATH + 1)
            GetSystemDirectoryW(buffer, len(buffer))
            return buffer.value
        return GetSystemDirectory
    GetSystemDirectory = GetSystemDirectory()
    
    def GetVolumeSerialNumber():
        GetVolumeInformationW = kernel32.GetVolumeInformationW
        GetVolumeInformationW.argtypes = [c_wchar_p, c_wchar_p, c_uint,
                                          POINTER(c_uint), POINTER(c_uint),
                                          POINTER(c_uint), c_wchar_p, c_uint]
        GetVolumeInformationW.restype = c_uint
        def GetVolumeSerialNumber(path):
            vsn = c_uint(0)
            GetVolumeInformationW(
                path, None, 0, byref(vsn), None, None, None, 0)
            return vsn.value
        return GetVolumeSerialNumber
    GetVolumeSerialNumber = GetVolumeSerialNumber()
    
    def GetUserName():
        GetUserNameW = advapi32.GetUserNameW
        GetUserNameW.argtypes = [c_wchar_p, POINTER(c_uint)]
        GetUserNameW.restype = c_uint
        def GetUserName():
            buffer = create_unicode_buffer(32)
            size = c_uint(len(buffer))
            while not GetUserNameW(buffer, byref(size)):
                buffer = create_unicode_buffer(len(buffer) * 2)
                size.value = len(buffer)
            return buffer.value.encode('utf-16-le')[::2]
        return GetUserName
    GetUserName = GetUserName()
    
    PAGE_EXECUTE_READWRITE = 0x40
    MEM_COMMIT  = 0x1000
    MEM_RESERVE = 0x2000
    
    def VirtualAlloc():
        _VirtualAlloc = kernel32.VirtualAlloc
        _VirtualAlloc.argtypes = [LPVOID, c_size_t, DWORD, DWORD]
        _VirtualAlloc.restype = LPVOID
        def VirtualAlloc(addr, size, alloctype=(MEM_COMMIT | MEM_RESERVE),
                         protect=PAGE_EXECUTE_READWRITE):
            return _VirtualAlloc(addr, size, alloctype, protect)
        return VirtualAlloc
    VirtualAlloc = VirtualAlloc()
    
    MEM_RELEASE = 0x8000
    
    def VirtualFree():
        _VirtualFree = kernel32.VirtualFree
        _VirtualFree.argtypes = [LPVOID, c_size_t, DWORD]
        _VirtualFree.restype = BOOL
        def VirtualFree(addr, size=0, freetype=MEM_RELEASE):
            return _VirtualFree(addr, size, freetype)
        return VirtualFree
    VirtualFree = VirtualFree()
    
    class NativeFunction(object):
        def __init__(self, restype, argtypes, insns):
            self._buf = buf = VirtualAlloc(None, len(insns))
            memmove(buf, insns, len(insns))
            ftype = CFUNCTYPE(restype, *argtypes)
            self._native = ftype(buf)
    
        def __call__(self, *args):
            return self._native(*args)
    
        def __del__(self):
            if self._buf is not None:
                VirtualFree(self._buf)
                self._buf = None
    
    if struct.calcsize("P") == 4:
        CPUID0_INSNS = (
            "\x53"             # push   %ebx
            "\x31\xc0"         # xor    %eax,%eax
            "\x0f\xa2"         # cpuid
            "\x8b\x44\x24\x08" # mov    0x8(%esp),%eax
            "\x89\x18"         # mov    %ebx,0x0(%eax)
            "\x89\x50\x04"     # mov    %edx,0x4(%eax)
            "\x89\x48\x08"     # mov    %ecx,0x8(%eax)
            "\x5b"             # pop    %ebx
            "\xc3"             # ret
        )
        CPUID1_INSNS = (
            "\x53"             # push   %ebx
            "\x31\xc0"         # xor    %eax,%eax
            "\x40"             # inc    %eax
            "\x0f\xa2"         # cpuid
            "\x5b"             # pop    %ebx
            "\xc3"             # ret
        )
    else:
        CPUID0_INSNS = (
            "\x49\x89\xd8"     # mov    %rbx,%r8
            "\x49\x89\xc9"     # mov    %rcx,%r9
            "\x48\x31\xc0"     # xor    %rax,%rax
            "\x0f\xa2"         # cpuid
            "\x4c\x89\xc8"     # mov    %r9,%rax
            "\x89\x18"         # mov    %ebx,0x0(%rax)
            "\x89\x50\x04"     # mov    %edx,0x4(%rax)
            "\x89\x48\x08"     # mov    %ecx,0x8(%rax)
            "\x4c\x89\xc3"     # mov    %r8,%rbx
            "\xc3"             # retq
        )
        CPUID1_INSNS = (
            "\x53"             # push   %rbx
            "\x48\x31\xc0"     # xor    %rax,%rax
            "\x48\xff\xc0"     # inc    %rax
            "\x0f\xa2"         # cpuid
            "\x5b"             # pop    %rbx
            "\xc3"             # retq
        )
    
    def cpuid0():
        _cpuid0 = NativeFunction(None, [c_char_p], CPUID0_INSNS)
        buf = create_string_buffer(12)
        def cpuid0():
            _cpuid0(buf)
            return buf.raw
        return cpuid0
    cpuid0 = cpuid0()
    
    cpuid1 = NativeFunction(c_uint, [], CPUID1_INSNS)
    
    class DataBlob(Structure):
        _fields_ = [('cbData', c_uint),
                    ('pbData', c_void_p)]
    DataBlob_p = POINTER(DataBlob)
    
    def CryptUnprotectData():
        _CryptUnprotectData = crypt32.CryptUnprotectData
        _CryptUnprotectData.argtypes = [DataBlob_p, c_wchar_p, DataBlob_p,
                                       c_void_p, c_void_p, c_uint, DataBlob_p]
        _CryptUnprotectData.restype = c_uint
        def CryptUnprotectData(indata, entropy):
            indatab = create_string_buffer(indata)
            indata = DataBlob(len(indata), cast(indatab, c_void_p))
            entropyb = create_string_buffer(entropy)
            entropy = DataBlob(len(entropy), cast(entropyb, c_void_p))
            outdata = DataBlob()
            if not _CryptUnprotectData(byref(indata), None, byref(entropy),
                                       None, None, 0, byref(outdata)):
                raise ADEPTError("Failed to decrypt user key key (sic)")
            return string_at(outdata.pbData, outdata.cbData)
        return CryptUnprotectData
    CryptUnprotectData = CryptUnprotectData()
    
    def retrieve_key():
        if _aes is None:
            raise ADEPTError("Couldn\'t load PyCrypto")
        root = GetSystemDirectory().split('\\')[0] + '\\'
        serial = GetVolumeSerialNumber(root)
        vendor = cpuid0()
        signature = struct.pack('>I', cpuid1())[1:]
        user = GetUserName()
        entropy = struct.pack('>I12s3s13s', serial, vendor, signature, user)
        cuser = winreg.HKEY_CURRENT_USER
        try:
            regkey = winreg.OpenKey(cuser, DEVICE_KEY_PATH)
        except WindowsError:
            raise ADEPTError("Adobe Digital Editions not activated")
        device = winreg.QueryValueEx(regkey, 'key')[0]
        keykey = CryptUnprotectData(device, entropy)
        userkey = None
        try:
            plkroot = winreg.OpenKey(cuser, PRIVATE_LICENCE_KEY_PATH)
        except WindowsError:
            raise ADEPTError("Could not locate ADE activation")
        for i in xrange(0, 16):
            try:
                plkparent = winreg.OpenKey(plkroot, "%04d" % (i,))
            except WindowsError:
                break
            ktype = winreg.QueryValueEx(plkparent, None)[0]
            if ktype != 'credentials':
                continue
            for j in xrange(0, 16):
                try:
                    plkkey = winreg.OpenKey(plkparent, "%04d" % (j,))
                except WindowsError:
                    break
                ktype = winreg.QueryValueEx(plkkey, None)[0]
                if ktype != 'privateLicenseKey':
                    continue
                userkey = winreg.QueryValueEx(plkkey, 'value')[0]
                break
            if userkey is not None:
                break
        if userkey is None:
            raise ADEPTError('Could not locate privateLicenseKey')
        userkey = userkey.decode('base64')
        userkey = _aes.new(keykey, _aes.MODE_CBC).decrypt(userkey)
        userkey = userkey[26:-ord(userkey[-1])]
        return userkey

else:

    import xml.etree.ElementTree as etree
    import Carbon.File
    import Carbon.Folder
    import Carbon.Folders
    import MacOS
    
    ACTIVATION_PATH = 'Adobe/Digital Editions/activation.dat'
    NSMAP = {'adept': 'http://ns.adobe.com/adept',
             'enc': 'http://www.w3.org/2001/04/xmlenc#'}
    
    def find_folder(domain, dtype):
        try:
            fsref = Carbon.Folder.FSFindFolder(domain, dtype, False)
            return Carbon.File.pathname(fsref)
        except MacOS.Error:
            return None
    
    def find_app_support_file(subpath):
        dtype = Carbon.Folders.kApplicationSupportFolderType
        for domain in Carbon.Folders.kUserDomain, Carbon.Folders.kLocalDomain:
            path = find_folder(domain, dtype)
            if path is None:
                continue
            path = os.path.join(path, subpath)
            if os.path.isfile(path):
                return path
        return None
    
    def retrieve_key():
        actpath = find_app_support_file(ACTIVATION_PATH)
        if actpath is None:
            raise ADEPTError("Could not locate ADE activation")
        tree = etree.parse(actpath)
        adept = lambda tag: '{%s}%s' % (NSMAP['adept'], tag)
        expr = '//%s/%s' % (adept('credentials'), adept('privateLicenseKey'))
        userkey = tree.findtext(expr)
        userkey = userkey.decode('base64')
        userkey = userkey[26:]
        return userkey
