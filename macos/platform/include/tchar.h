#pragma once
#ifdef _UNICODE
#error The current native build profile uses the ANSI TCHAR SDK variant
#endif
using TCHAR = char;
using LPTSTR = char*;
using LPCTSTR = const char*;
#define _T(value) value
#define TEXT(value) value
