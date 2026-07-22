"""測試 TDX 路況服務：python -m app.services.tdx_traffic_test"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from app.services import tdx_traffic

print("正在取得 TDX VD 路況資料（新北市）...")
ok = tdx_traffic.refresh()
if not ok:
    print("取得失敗（請確認 TDX_CLIENT_ID / TDX_CLIENT_SECRET 已設定）")
    sys.exit(1)

factors = tdx_traffic.get_district_factors()
congestion = tdx_traffic.get_congestion_level()

print(f"\n成功取得 {len(factors)} 個行政區路況")
print(f"整體壅塞程度：{congestion*100:.1f}%\n")

print("行政區路況係數（<1.0 表示塞車）：")
for dist, factor in sorted(factors.items(), key=lambda x: x[1]):
    status = "塞車" if factor < 0.6 else ("偏慢" if factor < 0.85 else "正常")
    adj = f"{(1/factor - 1)*100:+.0f}%" if factor < 0.99 else "正常"
    print(f"  [{status}] {dist:<6} 係數={factor:.2f}  行程時間{adj}")
