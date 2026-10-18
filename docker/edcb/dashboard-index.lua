-- Generated from the Vite HTML at image build time. This file is a Lua script.
local ct = __DASHBOARD_BODY__

local function ImfFixdate(t)
  return ('%s, %02d %s %d %02d:%02d:%02d GMT'):format(({'Sun','Mon','Tue','Wed','Thu','Fri','Sat'})[t.wday],t.day,
    ({'Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'})[t.month],t.year,t.hour,t.min,t.sec)
end

mg.write('HTTP/1.1 200 OK'
  ..'\r\nDate: '..ImfFixdate(os.date('!*t'))
  ..'\r\nContent-Type: text/html; charset=utf-8'
  ..'\r\nCache-Control: no-cache'
  ..(mg.request_info.request_method~='HEAD' and '\r\nContent-Length: '..#ct or '')
  ..(mg.keep_alive(true) and '' or '\r\nConnection: close')
  ..'\r\n\r\n'
  ..(mg.request_info.request_method~='HEAD' and ct or ''))
