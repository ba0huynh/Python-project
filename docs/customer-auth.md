# API tài khoản khách hàng

Backend Django + PostgreSQL dành cho khách hàng của app xe ôm công nghệ.
Base URL khi chạy local: `http://127.0.0.1:8000/api/auth/`.
Tất cả POST gửi `Content-Type: application/json`.

## Cài đặt và chạy trên Windows

Yêu cầu Python 3.12 và Docker Desktop đang chạy Linux containers.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Chỉ copy `.env.example` lần đầu, không ghi đè `.env` đã có. Đặt `SECRET_KEY`
ngẫu nhiên riêng trong `.env`; file này được Git bỏ qua. Máy hiện tại đã được
tạo `.env`, môi trường ảo và áp dụng migration trên PostgreSQL.

## Các endpoint

| Method | Đường dẫn | Xác thực | Kết quả thành công |
| --- | --- | --- | --- |
| POST | `register/` | Không | 201, hồ sơ và cặp JWT |
| POST | `login/` | Không | 200, hồ sơ và cặp JWT |
| POST | `refresh/` | Refresh token trong JSON | 200, cặp JWT mới |
| GET | `me/` | Bearer access token | 200, hồ sơ khách hàng |
| POST | `logout/` | Bearer access token và refresh token trong JSON | 204, không có body |

### Đăng ký

```json
{
  "phone": "0912345678",
  "full_name": "Nguyễn Văn An",
  "email": "an@example.com",
  "password": "RideSecure!2026",
  "password_confirm": "RideSecure!2026"
}
```

`email` không bắt buộc. Số điện thoại là định danh đăng nhập duy nhất;
`0912345678` và `+84912345678` cùng một tài khoản. Chỉ chấp nhận định dạng
số di động Việt Nam 10 chữ số hoặc dạng `+84` tương ứng, không có dấu cách.
Mật khẩu được kiểm tra bằng validators của Django và lưu dưới dạng băm.
Không nhận quyền admin/staff từ dữ liệu đăng ký.

Đăng ký và đăng nhập trả về:

```json
{
  "customer": {
    "id": "<uuid>",
    "phone": "+84912345678",
    "full_name": "Nguyễn Văn An",
    "email": "an@example.com",
    "created_at": "<ISO-8601>"
  },
  "access": "<access-token>",
  "refresh": "<refresh-token>"
}
```

### Đăng nhập

```json
{"phone": "0912345678", "password": "RideSecure!2026"}
```

### Hồ sơ của tôi

Gọi `GET /api/auth/me/` với header:

```text
Authorization: Bearer <access-token>
```

Kết quả là object hồ sơ giống trường `customer` ở trên, không có mật khẩu.

### Làm mới token

Gọi `POST /api/auth/refresh/`:

```json
{"refresh": "<refresh-token>"}
```

Access token sống 5 phút, refresh token sống 7 ngày. Mỗi lần refresh thành công,
frontend phải lưu cả hai token mới và thay token cũ. Refresh token cũ bị thu hồi;
frontend cần tránh gửi nhiều yêu cầu refresh đồng thời.

### Đăng xuất

Gọi `POST /api/auth/logout/` với Bearer access token và JSON:

```json
{"refresh": "<refresh-token>"}
```

Chỉ được thu hồi refresh token của tài khoản hiện tại. Sau đó frontend xóa token
đang lưu. Access token đã phát hành vẫn có hiệu lực đến hết thời hạn tối đa
5 phút; đăng xuất chỉ kết thúc phiên của refresh token được gửi, không phải
tất cả thiết bị. Tài khoản bị vô hiệu hóa không được truy cập API hoặc refresh.

## Lỗi và kiểm thử

- 400: thiếu/sai dữ liệu, trùng số điện thoại, mật khẩu sai hoặc xác nhận không khớp.
- 401: thiếu access token, JWT sai/hết hạn, hoặc refresh token đã bị thu hồi.
- 403: cố thu hồi token của người khác hoặc user không có hồ sơ khách hàng.
- 429: quá giới hạn 10 yêu cầu/phút/IP dùng chung cho đăng ký, đăng nhập và refresh.
- 405/415: phương thức hoặc Content-Type không được hỗ trợ.

Lỗi dữ liệu thường có dạng `{"phone": ["..."]}` hoặc
`{"non_field_errors": ["..."]}`; lỗi xác thực có trường `detail`.

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test accounts
```

Tests tạo và xóa database `test_django_db` riêng trên PostgreSQL. Tài khoản
database chạy test cần quyền tạo database. Không dùng database test đang chứa
dữ liệu quan trọng. Có 12 test kiểm tra các luồng chính và các trường hợp từ chối.

## Cấu trúc và phạm vi

- `accounts/models.py`: hồ sơ Customer kế thừa BaseModel, liên kết OneToOne
  với User mặc định của Django; username nội bộ là số điện thoại chuẩn hóa.
- `accounts/serializers.py`: kiểm tra dữ liệu, tạo tài khoản trong transaction.
- `accounts/views.py`: API và phát hành/thu hồi JWT bằng Simple JWT.
- `accounts/migrations/`: schema PostgreSQL; không thay đổi model User có sẵn.
- `/admin/`: quản lý hồ sơ, khóa tài khoản bằng `User.is_active`.

Chưa tích hợp OTP/SMS, quên mật khẩu, đăng nhập mạng xã hội hay tài khoản tài xế.
Số điện thoại đăng ký chưa được xác minh quyền sở hữu. Email không dùng để đăng nhập
và không có ràng buộc duy nhất. Chưa cấu hình CORS vì chưa biết origin của frontend;
mobile native/Postman không cần CORS. Frontend web chạy khác origin cần cấu hình
allowlist origin khi tích hợp.

Khi triển khai thật, dùng HTTPS, tắt DEBUG, đặt ALLOWED_HOSTS cụ thể, thay mật khẩu
database phát triển. Throttle hiện dùng cache bộ nhớ mỗi tiến trình của Django;
chạy nhiều worker cần cache dùng chung và giới hạn bổ sung ở proxy. Lên lịch chạy
`python manage.py flushexpiredtokens` hằng ngày để dọn token hết hạn.
