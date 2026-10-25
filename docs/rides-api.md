# API chuyến đi, tài xế, bản đồ đường đi và WebSocket

Base URL local: `http://<máy>:8000/api/`. Mọi request (trừ đăng ký/đăng nhập) gửi
`Authorization: Bearer <access token>` và `Content-Type: application/json`.
Toạ độ trong body luôn là `{"lat": ..., "lng": ...}`. Riêng `geometry` của route là
GeoJSON nên toạ độ là **`[lng, lat]`**, vẽ thẳng bằng MapLibre.

## Chạy

```powershell
docker compose up -d                       # Postgres (cổng lấy từ POSTGRES_PORT trong .env)
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed  # tài khoản mẫu, mật khẩu GoXe!2026
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000   # HTTP + WebSocket (daphne)
```

Tài khoản mẫu sau khi `seed`:

| Vai trò | SĐT | Xe |
|---|---|---|
| Khách | 0912345678, 0987654321 | |
| Tài xế | 0901234567, 0902345678 | bike |
| Tài xế | 0903456789 | car4 |
| Tài xế | 0904567890 | car7 |

Tài xế mẫu đang `ONLINE` quanh chợ Bến Thành (Quận 1).

## Geoapify (vẽ đường đi)

Đặt `GEOAPIFY_API_KEY` trong `.env` (miễn phí tại https://myprojects.geoapify.com).
Server gọi Geoapify Routing (`mode=motorcycle` cho xe máy, `drive` cho ô tô), gộp các
leg thành một `LineString` và lưu vào bảng `core_route`. Hai điểm làm tròn 4 chữ số thập
phân (~11 m), nên cùng một tuyến chỉ gọi API một lần.

Không có key hoặc Geoapify lỗi: server lưu đường thẳng ước lượng (`provider:
"straight_line"`, quãng đường x1.3, 25 km/h). Khi có key, lần gọi sau tự thay bằng đường thật.

Route object:

```json
{"id": "<uuid>", "mode": "motorcycle", "distance_m": 4690, "duration_s": 780,
 "provider": "geoapify", "geometry": {"type": "LineString", "coordinates": [[106.6981, 10.7725], ...]}}
```

## Tài khoản tài xế (`/api/auth/driver/`)

| Method | Đường dẫn | Body | Kết quả |
|---|---|---|---|
| POST | `register/` | `phone, full_name, password, password_confirm, license_number, vehicle_plate, vehicle_type (bike/car4/car7), vehicle_name?` | 201 `{driver, access, refresh}` |
| POST | `login/` | `phone, password` | 200 `{driver, access, refresh}` |
| GET | `me/` | | hồ sơ tài xế |

`refresh/` và `logout/` dùng chung với khách. Tài khoản tài xế tách riêng với tài khoản
khách (username `driver:<sđt>`), nên một số điện thoại có thể có cả hai. Tài xế mới được duyệt
tự động khi `DRIVER_AUTO_APPROVE=True`; nếu không, duyệt trong `/admin`.

## Khách hàng

| Method | Đường dẫn | Body | Ghi chú |
|---|---|---|---|
| POST | `rides/estimate/` | `{pickup, dropoff}` | `{options: [{vehicle_type, name, seats, fare, route}]}` |
| POST | `rides/` | `{vehicle_type, pickup:{lat,lng,address}, dropoff:{...}}` | 201 ride `PENDING`, báo tài xế gần nhất |
| GET | `rides/` | | lịch sử (50 chuyến gần nhất), dùng được cho cả tài xế |
| GET | `rides/current/` | | `{ride: ... | null}` chuyến đang chạy |
| GET | `rides/<id>/` | | chi tiết |
| POST | `rides/<id>/cancel/` | `{reason?}` | khách hủy được khi PENDING/ACCEPTED/ARRIVED |
| POST | `rides/<id>/rate/` | `{rating: 1-5, comment?}` | sau khi COMPLETED, một lần |

Mỗi khách chỉ có một chuyến đang chạy. Giá cước (VND, làm tròn 1.000đ): giá mở cửa cho 2 km
đầu + giá mỗi km sau đó, giống `mobile/src/lib/mock.ts`:

| Loại | Mở cửa | Mỗi km |
|---|---|---|
| bike | 12.000 | 4.500 |
| car4 | 25.000 | 9.000 |
| car7 | 30.000 | 11.000 |

## Tài xế (`/api/driver/`)

| Method | Đường dẫn | Body | Ghi chú |
|---|---|---|---|
| PATCH | `status/` | `{status: ONLINE|OFFLINE, lat?, lng?}` | phải được duyệt; không đổi được khi BUSY |
| POST | `location/` | `{lat, lng}` | dự phòng, nên gửi qua WebSocket |
| GET | `rides/available/` | | cuốc PENDING cùng loại xe trong bán kính `DRIVER_SEARCH_RADIUS_KM` (5 km) |
| POST | `rides/<id>/accept/` | | khoá dòng để hai tài xế không nhận trùng; tính `approach_route` |
| PATCH | `rides/<id>/update-status/` | `{status}` | chỉ đi tiếp từng bước |
| POST | `/api/rides/<id>/cancel/` | `{reason?}` | tài xế hủy: chuyến về PENDING và gửi lại cho tài xế khác |

Luồng trạng thái:

```
PENDING -> ACCEPTED -> ARRIVED -> IN_PROGRESS -> COMPLETED
PENDING / ACCEPTED / ARRIVED -> CANCELLED (khách hủy)
ACCEPTED / ARRIVED -> PENDING (tài xế hủy)
```

Trạng thái tài xế: `OFFLINE` -> `ONLINE` -> (nhận cuốc) `BUSY` -> (hoàn thành / bị hủy) `ONLINE`.

## WebSocket

```
ws://<máy>:8000/ws/?token=<access token>
```

Token sai/thiếu: đóng với mã `4401`. Access token sống 5 phút, nên khi kết nối lại thì
refresh token trước. Mỗi tin nhắn từ server có dạng `{"event": "...", "data": {...}}`:

| event | Gửi cho | data |
|---|---|---|
| `connected` | người vừa kết nối | `{user_id}` |
| `ride.requested` | tài xế ONLINE gần điểm đón, đúng loại xe | ride + `distance_to_pickup_m` |
| `ride.unavailable` | tài xế từng được mời | `{id}` (đã có người nhận / bị hủy) |
| `ride.updated` | khách và tài xế của chuyến | ride đầy đủ |
| `driver.location` | khách của chuyến đang chạy | `{ride_id, lat, lng}` |
| `pong` / `error` | người gửi | |

Client gửi lên:

```json
{"type": "ping"}
{"type": "driver.location", "lat": 10.776, "lng": 106.70}
```

Tài xế nên gửi `driver.location` vài giây một lần khi ONLINE. Server lưu vị trí và, nếu đang
có chuyến, chuyển ngay cho khách.

Channel layer mặc định là in-memory (một tiến trình server là đủ khi demo). Chạy nhiều tiến
trình thì đặt `REDIS_URL` và `pip install channels-redis`.

## Bảng dữ liệu (app `core`)

- `core_driverprofile`: tài xế, xe, trạng thái, vị trí hiện tại, điểm đánh giá.
- `core_ride`: chuyến đi, điểm đón/trả (địa chỉ + toạ độ), quãng đường, giá, trạng thái và
  thời điểm từng bước, ai hủy, đánh giá.
- `core_route`: đường đi đã lấy từ Geoapify (cache), `geometry` GeoJSON.
- `accounts_customer`: khách hàng (đã có từ trước).
