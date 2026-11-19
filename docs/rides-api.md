# GoXe API: chuyến đi, tài xế, địa điểm, realtime

Tất cả endpoint dưới `/api/`, JSON, xác thực `Authorization: Bearer <access>` (trừ `/api/health/`).
Lỗi theo kiểu DRF: `{"detail": "..."}` hoặc `{"field": ["..."]}`. Toạ độ trong body là `{lat, lng}`;
hình học GeoJSON là `[lng, lat]`. Tiền là số nguyên VND, làm tròn 1.000đ.

Tài khoản và OTP: xem [customer-auth.md](customer-auth.md).

## Giá cước (theo km) và phí nền tảng

Bảng giá nằm trong bảng `FareRule` (sửa ở `/admin` → *Fare rules*, không cần deploy):

```
cước = base_fare + per_km × max(0, km − base_km), tối thiểu minimum_fare, làm tròn 1.000đ
phí nền tảng (commission) = cước × commission_percent %, làm tròn 1.000đ
tài xế nhận (driver_earning) = cước − commission
```

| Loại | base_fare (2 km đầu) | per_km | tối thiểu | phí nền tảng |
|---|---|---|---|---|
| `bike` GoBike | 12.000 | 4.500 | 12.000 | 20% |
| `car4` GoCar 4 chỗ | 25.000 | 9.000 | 25.000 | 20% |
| `car7` GoCar 7 chỗ | 30.000 | 11.000 | 30.000 | 20% |

Giá **chốt lúc đặt** (upfront): số tiền trong `estimate` là số khách trả. Thanh toán tiền mặt:
tài xế thu `fare` từ khách; nền tảng thu `commission` từ tài xế. Quãng đường lấy từ Geoapify
(đường thật); không có key thì dùng đường chim bay × 1,3.

## Ghép tài xế (dispatch)

1. Đặt xe → chuyến `PENDING`, gửi **lời mời** (`RideOffer`) tới `DISPATCH_BATCH_SIZE` (3) tài xế
   gần nhất thỏa: `ONLINE`, đã duyệt, đúng loại xe, trong `DRIVER_SEARCH_RADIUS_KM` (5 km),
   GPS mới trong `DRIVER_LOCATION_MAX_AGE_SECONDS` (120 s), không đang giữ lời mời khác.
2. Mỗi lời mời sống `DRIVER_OFFER_SECONDS` (15 s). Ai nhận trước thì được; người còn lại nhận
   `ride.offer_cancelled` (`taken`).
3. Khi mọi lời mời đã bị từ chối / hết hạn, đợt tiếp theo được gửi (kể cả tài xế mới bật app).
   Tài xế đã từ chối, để hết hạn hoặc đã hủy không được mời lại chuyến đó.
4. Không ai nhận trong `RIDE_SEARCH_SECONDS` (180 s) → chuyến `CANCELLED`, `cancelled_by="system"`,
   `cancel_reason="Không tìm thấy tài xế phù hợp."`.
5. Bước 3–4 do **dispatcher** chạy mỗi 2 s: tự chạy trong web server khi không có Redis
   (`RIDE_WORKER_EMBEDDED`), hoặc tiến trình riêng `python manage.py ride_worker` khi có Redis.

Trạng thái: `PENDING → ACCEPTED → ARRIVED → IN_PROGRESS → COMPLETED`; khách hủy được khi
`PENDING/ACCEPTED/ARRIVED`; tài xế hủy khi `ACCEPTED/ARRIVED` → chuyến quay lại `PENDING` và được
mời tài xế khác. "Đã đến" chỉ hợp lệ khi tài xế cách điểm đón ≤ `DRIVER_ARRIVAL_RADIUS_M` (300 m).

## Đối tượng

**Ride**
```json
{
  "id": "uuid", "status": "PENDING", "vehicle_type": "bike",
  "pickup": {"address": "Chợ Bến Thành", "lat": 10.7725, "lng": 106.6981},
  "dropoff": {"address": "Landmark 81", "lat": 10.795, "lng": 106.7219},
  "distance_m": 4200, "duration_s": 780, "fare": 22000, "payment_method": "cash",
  "customer": {"id": "uuid", "full_name": "…", "phone": "+849…"},
  "driver": {"id": "uuid", "full_name": "…", "phone": "+849…", "vehicle_type": "bike",
             "vehicle_name": "Honda Vision · Đỏ", "vehicle_plate": "59X2-123.45", "rating": 4.9,
             "lat": 10.77, "lng": 106.70, "heading": 90.0},
  "route": {"id": "uuid", "mode": "motorcycle", "distance_m": 4200, "duration_s": 780,
            "geometry": {"type": "LineString", "coordinates": [[106.6981, 10.7725], "…"]},
            "provider": "geoapify"},
  "approach_route": null,
  "created_at": "…", "accepted_at": null, "arrived_at": null, "started_at": null,
  "completed_at": null, "cancelled_at": null, "cancelled_by": "", "cancel_reason": "",
  "rating": null, "rating_comment": "", "search_expires_at": "…",
  "driver_earning": 18000, "commission": 4000
}
```
- `driver_earning`, `commission`: chỉ có khi người xem là tài xế của chuyến (hoặc trong lời mời).
- `approach_route`: vị trí tài xế lúc nhận → điểm đón.
- `search_expires_at`: hạn tìm tài xế khi `PENDING`, ngược lại `null`.

**Offer** (lời mời cho tài xế): `{offer_id, ride_id, expires_at, expires_in, distance_to_pickup_m, ride}`.
`expires_in` là số giây còn lại (dùng cho đồng hồ đếm ngược, không phụ thuộc giờ điện thoại).
`ride.customer.phone` để trống cho tới khi tài xế nhận chuyến.

## Endpoint

| Method | Đường dẫn | Ai | Mô tả |
|---|---|---|---|
| GET | `health/` | công khai | `{"status": "ok"}` (kiểm tra DB) |
| POST | `rides/estimate/` | khách | `{pickup, dropoff}` → `{options: [{vehicle_type, name, seats, fare, distance_m, duration_s, route, drivers_nearby}]}` |
| POST | `rides/` | khách | `{vehicle_type, pickup{lat,lng,address}, dropoff{…}}` → 201 Ride. 400 nếu đang có chuyến |
| GET | `rides/?limit=20&offset=0` | cả hai | `{count, next, previous, results: Ride[]}` (khách: chuyến đã đặt; tài xế: chuyến đã chạy) |
| GET | `rides/current/` | cả hai | `{ride: Ride \| null}` chuyến đang diễn ra |
| GET | `rides/<id>/` | cả hai | chi tiết chuyến của mình |
| POST | `rides/<id>/cancel/` | cả hai | `{reason?}` → Ride |
| POST | `rides/<id>/rate/` | khách | `{rating: 1-5, comment?}` → Ride (một lần) |
| PATCH | `driver/status/` | tài xế | `{status: ONLINE\|OFFLINE, lat, lng}` (bật cần GPS; chưa duyệt → 403) |
| POST | `driver/location/` | tài xế | `{lat, lng, heading?}` → 204 (dự phòng khi mất WebSocket) |
| GET | `driver/offers/` | tài xế | `{offers: Offer[]}` lời mời đang mở (0 hoặc 1) |
| POST | `driver/rides/<id>/accept/` | tài xế | → Ride. 400 nếu lời mời hết hạn / đã có người nhận |
| POST | `driver/rides/<id>/decline/` | tài xế | → 204, chuyển lời mời cho tài xế kế tiếp |
| PATCH | `driver/rides/<id>/update-status/` | tài xế | `{status: ARRIVED\|IN_PROGRESS\|COMPLETED}` → Ride |
| GET | `driver/earnings/` | tài xế | `{today, week, month: {trips, gross, commission, net}, recent: Ride[]}` (giờ Việt Nam) |
| GET | `geo/search/?q=&lat=&lng=` | đăng nhập | `{results: [{name, address, lat, lng}]}` (q ≥ 2 ký tự, ưu tiên gần lat/lng) |
| GET | `geo/reverse/?lat=&lng=` | đăng nhập | `{name, address, lat, lng}` |

Giới hạn tần suất (mỗi người dùng): estimate 30/phút, đặt xe 10/phút, geo 60/phút,
vị trí REST 120/phút, chung 300/phút → 429.

## WebSocket `/ws/?token=<access>`

Token sai / hết hạn → đóng với mã **4401** (làm mới token rồi kết nối lại).
Sau mỗi lần (re)connect server gửi `connected`; client nên tải lại trạng thái
(`rides/current/`, `driver/offers/`) vì có thể đã lỡ sự kiện.

Server → client `{"event", "data"}`:

| event | Gửi tới | data |
|---|---|---|
| `connected` | mọi người | `{user_id}` |
| `ride.offer` | tài xế | Offer |
| `ride.offer_cancelled` | tài xế | `{ride_id, offer_id, reason: taken\|cancelled\|expired}` |
| `ride.updated` | khách + tài xế | Ride (mỗi bên nhận góc nhìn của mình) |
| `driver.location` | khách | `{ride_id, lat, lng, heading}` |
| `pong` / `error` | người gửi | – / `{detail}` |

Client → server: `{"type": "ping"}`; tài xế gửi
`{"type": "driver.location", "lat": …, "lng": …, "heading": …}` (tối đa 1 lần/giây, nên gửi mỗi
~4 s khi di chuyển và ít nhất mỗi 20 s khi đứng yên để không bị coi là mất GPS).
