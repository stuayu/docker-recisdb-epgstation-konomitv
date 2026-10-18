const timeFormatter = new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const dateFormatter = new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', month: '2-digit', day: '2-digit' })
export function time(value: string | number) { return timeFormatter.format(new Date(value)) }
export function shortDate(value: string | number) { return dateFormatter.format(new Date(value)) }
export function duration(seconds: number) {
  const minutes = Math.ceil(seconds / 60)
  return minutes >= 60 ? `${Math.floor(minutes / 60)}時間${minutes % 60 ? `${minutes % 60}分` : ''}` : `${minutes}分`
}
