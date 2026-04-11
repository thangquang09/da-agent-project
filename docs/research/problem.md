Đừng bao giờ coi thường một nghề mà bạn chưa thực sự hiểu!
Tôi phát ốm với những content kiểu "cho team Data Analytics nghỉ hưu sớm." như này!
Lâu nay tôi thấy rất nhiều bài đăng dạng: connect Data vào tool AI, kéo được vài cái bảng report cơ bản, render ra mấy cái chart cơ bản — rồi caption đầy tự tin: "Giờ đây có thể cho team Data Analytics nghỉ hưu sớm/ ra chuồng gà..."
Tôi không có ý công kích ai. Nhưng tôi muốn nói thay cho hàng nghìn người đang làm Data Analytics chuyên nghiệp mỗi ngày, đang âm thầm nỗ lực, làm Analytics một cách bài bản. Để doanh nghiệp Việt cũng có thể đưa ra những quyết định dữ liệu thực sự chất lượng & giá trị giống như doanh nghiệp quốc tế đang làm. Nhưng đang âm thầm đọc những dòng caption đó và thấy nghề mình bị coi nhẹ...
Bạn vừa làm được gì?
Bạn connect 1 MCP server, gọi API lấy raw data, rồi nhờ AI render 1 cái dashboard.
Chúc mừng. Bạn vừa làm được bước 1 trong khoảng 20 bước của một quy trình Analytics thực tế.
Bạn biết DA đang làm gì mỗi ngày không?
→ Thiết kế Data Model chuẩn Star Schema / Snowflake cho hàng chục bảng, hàng triệu dòng — đảm bảo mỗi con số trình lên lãnh đạo là chính xác, nhất quán, có thể kiểm chứng — không phải kiểu "AI generate ra sao thì tin vậy"
→ Viết DAX / SQL phức tạp để tính các KPI có logic nghiệp vụ đặc thù từng ngành — những công thức mà nếu sai 1 dòng, sai cả chiến lược
→ Xây dựng các loại Business Tree để phân tích nguyên nhân gốc rễ — không phải chỉ "vẽ chart đẹp"
→ Đảm bảo Data Quality: xử lý missing values, outliers, duplicates, validate business rules — trước khi bất kỳ con số nào được trình lên lãnh đạo
→ Thiết kế hệ thống phân quyền & bảo mật dữ liệu nghiêm ngặt: Row-Level Security, Object-Level Security, Workspace Roles — để đúng người chỉ xem đúng dữ liệu của mình. Sales Manager chỉ thấy data vùng mình quản lý. Finance chỉ thấy data Finance. Đây là yêu cầu bắt buộc của mọi doanh nghiệp — không phải thứ AI render ra 1 cái chart là xong
→ Thiết kế dashboard không phải 1-2 trang cơ bản, mà là hệ thống 10-20+ trang với drill-through, bookmarks, tooltips, dynamic filtering, conditional formatting — cho nhiều phòng ban, nhiều chủ đề, phục vụ hàng trăm users đồng thời với hiệu năng ổn định
→ Không chỉ report: mà là alerting, anomaly detection, forecasting, what-if analysis, paginated reports cho đối soát tài chính — những tính năng mà một cái chart AI render ra không bao giờ chạm tới
→ Storytelling bằng data để C-level ra quyết định kinh doanh trị giá hàng tỷ đồng — dựa trên Insight có cấu trúc, có luận điểm, có recommendation — không phải mô tả chart
Cái bạn vừa demo — DA làm được trong 5 phút. Nhưng cái DA đang làm — bạn chưa chạm tới.
Vấn đề không phải AI. Vấn đề là bạn chưa hiểu Analytics.
DA giờ làm Agentic AI Analytics. Build Agentic BI Kit với nhiều Agents, mỗi Agent nhiều Skills. 
LLM tool là brain, Fabric là execution layer, Power BI là delivery layer. Data Analyst giờ biết AI mạnh đến đâu — chính vì vậy càng biết rõ: AI không thay thế DA. AI cần DA giỏi để điều khiển nó.
Một người DA giỏi + Agentic AI = x100 output.
Một người không hiểu Analytics + AI = một đống chart đẹp nhưng sai insight.
Nên trước khi caption "cho DA nghỉ hưu", hãy tự hỏi:
◾ Bạn đã phân biệt được Measure và Calculated Column chưa?
◾ Bạn đã xây được một Semantic Model chuẩn chưa?
◾ Bạn đã từng ngồi với business để map KPI thành KPI Tree chưa? 
◾Bạn biết hệ thống tất cả hướng phân tích với các loại Business Tree khác nhau chưa?
◾ Bạn đã xử lý được Query Folding, Incremental Refresh chưa? Để hàng triệu dòng data refresh trong vài phút thay vì treo máy hàng giờ?
◾ Bạn đã thiết kế Row-Level Security cho hàng trăm user, đảm bảo không ai thấy data không thuộc phạm vi của mình chưa?
◾ Bạn đã build được alerting tự động khi KPI lệch khỏi ngưỡng, hay what-if scenario để C-level mô phỏng trước khi ra quyết định chưa?
◾ Bạn đã viết được 1 trang Insight/ Data Story đúng nghĩa — không phải mô tả chart — chưa?
Nếu chưa, thì cái bạn vừa demo là một cái toy. Không phải Analytics.
Tóm lại:
Đừng nhầm lẫn giữa "kết nối được data" với "làm được Analytics."
Đừng nhầm lẫn giữa "render được chart" với "ra được Insight."
Đừng nhầm lẫn giữa "1 người xem demo" với "hàng trăm người dùng thực tế mỗi ngày, mỗi người chỉ thấy đúng data của mình, với tốc độ và độ chính xác không được phép sai."
Và đừng bao giờ coi thường một nghề mà bạn chưa thực sự hiểu.
DA làm xịn, điều khiển Agentic AI, output x100.
Khi nào bạn làm xịn hơn DA đang làm — thì hẵng nói chuyện nghỉ hưu sớm. 💼 OK?