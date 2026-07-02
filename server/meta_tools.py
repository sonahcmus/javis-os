"""
meta_tools.py - Bộ "meta-capabilities" khởi đầu, seed vào mỗi brain (idempotent, create-if-missing).

Gồm:
  - Skill `javis-builder`: dạy Javis (chat chính) tạo agent/skill/workflow/loop ĐÚNG chuẩn,
    có chống trùng + kỷ luật nháp + rào an toàn. Gộp 4 "agent smith" thành 1 skill (rẻ, tự
    kích hoạt, đáng tin hơn spawn agent riêng).
  - Loop `tu-cai-tien-javis`: loop tự cải tiến Javis + ghi báo cáo (mặc định TẮT, suggest).
    Dùng lại engine loop sẵn có (loop = tự chạy prompt của nó; không cần agent riêng vì loop
    không gọi được workflow/agent).

Quy tắc làm-rõ-prompt nằm ở CLAUDE.md (system prompt) - rẻ, áp mọi lượt chat.

KHÔNG ghi đè file user đã có (create-if-missing). Xoá thì lần seed sau tạo lại (starter tools).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _today() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")


_SKILL_BUILDER = """---
name: Javis Builder
description: Kích hoạt khi người dùng muốn TẠO hoặc SỬA một năng lực của Javis - agent, skill, workflow, hoặc loop (vd "tạo agent chuyên X", "thêm kỹ năng Y", "dựng workflow nghiên cứu rồi viết", "tạo loop mỗi 2 tiếng làm Z", "làm cho Javis biết làm ..."). Đây là hướng dẫn cách ghi đúng file chuẩn của Javis.
group: AI
---

# Javis Builder - tạo agent / skill / workflow / loop

Khi người dùng muốn Javis có thêm một năng lực, bạn TỰ GHI FILE .md đúng chuẩn dưới đây vào
vault (brain đang chọn). Studio / trang tương ứng tự nhận file mới. Luôn báo cáo ngắn sau khi tạo.

## Quy trình (làm đúng thứ tự)

1. **Hiểu nhu cầu.** Nếu mô tả đủ rõ thì làm luôn; thiếu điểm cốt lõi (mục tiêu, đầu ra mong
   muốn) thì hỏi 1 câu ngắn rồi làm. Đừng hỏi lan man.
2. **Chọn đúng LOẠI năng lực:**
   - Việc trả lời/kiến thức cách-làm tái dùng nhiều lần -> **skill**.
   - Một "vai" chuyên môn có system prompt riêng -> **agent**.
   - Chuỗi nhiều bước, nhiều vai nối nhau -> **workflow** (tạo trước các agent còn thiếu).
   - Việc LẶP theo chu kỳ, tự chạy nền -> **loop**.
   - Việc làm 1 lần -> KHÔNG tạo gì, cứ làm luôn hoặc đề xuất task Kanban.
3. **Chống trùng.** TRƯỚC khi tạo, đọc folder tương ứng (agents/ workflows/ .claude/skills/
   loops/). Nếu đã có cái gần giống -> cập nhật cái cũ, đừng đẻ bản sao.
4. **Ghi file** đúng frontmatter (mẫu bên dưới). slug = ASCII không dấu, gạch nối. Tên hiển thị
   tiếng Việt. TUYỆT ĐỐI không dùng ký tự em dash, dùng "-".
5. **Báo cáo ngắn** bằng văn nói: đã tạo loại gì, tên/đường dẫn file, dùng ở đâu.

## Mẫu file (ghi CHÍNH XÁC theo đây)

### Agent -> `Javis/agents/<slug>.md`
```
---
type: agent
name: <Tên tiếng Việt>
slug: <ascii>
role: <vai trò 1 câu>
skills: [slug-skill]      # [] nếu chưa gán; chỉ gán skill đã có trong .claude/skills
model: ""                 # "" mặc định | sonnet|opus|haiku|fable (Claude) | gpt-5.5|gpt-5.4|gpt-5.3-codex (ChatGPT/Codex)
updated: <YYYY-MM-DD>
---
<system prompt: cách làm việc, nguyên tắc, định dạng đầu ra mong muốn>
```

### Skill -> `.claude/skills/<slug>/SKILL.md`
```
---
name: <Tên skill>
description: <mô tả NGẮN nêu rõ KHI NÀO kích hoạt - đây là trigger, viết kỹ>
group: <Marketing|Bán hàng|Nội dung|Vận hành|Tài chính|AI|Năng suất|Cá nhân>
---
<hướng dẫn chi tiết cho AI khi skill kích hoạt>
```

### Workflow -> `Javis/workflows/<slug>.md`
```
---
type: workflow
name: <Tên>
slug: <ascii>
status: off               # tạo mới để 'off' cho user xem trước rồi bật
description: <mô tả ngắn>
steps:
  - agent: <agent-slug>
    task: "<việc; {{input}}=đầu vào user, {{prev}}=kết quả bước trước>"
    verify_agent: <agent-slug>   # tùy chọn: agent soi lỗi
    max_retries: 1               # tùy chọn
updated: <YYYY-MM-DD>
---
<mô tả>
```
Nếu workflow tham chiếu agent chưa tồn tại -> TẠO agent đó trước.

### Loop -> `Javis/loops/<slug>.md`
```
---
type: loop
name: <Tên>
slug: <ascii>
enabled: false            # LUÔN tạo ở trạng thái TẮT
mode: suggest             # suggest=chỉ đọc/đề xuất | auto=tự ghi nháp an toàn | full=toàn quyền
interval_min: 120         # tối thiểu 5
updated: <YYYY-MM-DD>
---
<mô tả nhiệm vụ: mỗi vòng loop làm ĐÚNG việc này - đây chính là prompt của loop, viết tự-đủ>
```

## Rào an toàn (BẮT BUỘC)

- Loop tạo qua chat LUÔN `enabled: false` + `mode: suggest`. Chỉ nâng `mode: auto/full` hoặc bật
  ngay khi user yêu cầu RÕ RÀNG, và phải cảnh báo rủi ro (full = tự tạo đơn/tiêu tiền/đăng bài).
- KHÔNG tạo năng lực tự làm hành động tiền/đơn/quảng cáo/gửi tin/đăng bài mà không có người duyệt.
- KHÔNG bao giờ để một loop/automation tự tạo hoặc tự bật loop khác (chống phình vô hạn) - chỉ ĐỀ XUẤT.
- Skill/agent do TỰ ĐỘNG (loop/engine học) sinh ra -> để dạng nháp chờ duyệt. Skill do user yêu cầu
  trực tiếp -> tạo bật luôn nhưng phải kiểm trùng + `description` trigger rõ (skill rác làm Javis
  chọn skill sai). Đừng tạo skill trùng chức năng skill đã có.
- Sau khi tạo, KHÔNG tự chạy thứ có side-effect; để user xem trước.
"""


_LOOP_SELF_IMPROVE = """---
type: loop
name: Tự cải tiến Javis
slug: tu-cai-tien-javis
enabled: false
mode: suggest
interval_min: 720
updated: {today}
---
Đóng vai người cải tiến Javis. Mỗi vòng làm ĐÚNG các bước sau rồi dừng:

1. Rà nhanh: đọc log hội thoại gần đây (memory/conversations), các agent/workflow/skill/loop
   hiện có (Javis/agents, Javis/workflows, .claude/skills, Javis/loops), và nhật ký loop.
2. Nhận diện MỘT điểm đáng cải thiện nhất: người dùng hay vướng gì, yêu cầu gì lặp lại thủ công,
   thiếu agent/skill/workflow nào, chỗ nào gây khó.
3. Đề xuất (mode suggest) hoặc thực hiện (nếu user đã chuyển auto) ĐÚNG MỘT cải tiến nhỏ, an toàn:
   tạo/sửa 1 agent/skill/workflow (theo chuẩn của skill 'javis-builder'), hoặc ghi 1 note đề xuất.
4. Ghi BÁO CÁO ngắn vào '05 - Projects/Bao cao tu cai tien - {today}.md' (tạo nếu chưa có), gồm:
   (a) Quan sát gì, (b) Đề xuất/đã làm gì + file nào, (c) Cần chủ quyết gì.

RÀNG BUỘC: KHÔNG sửa code server. KHÔNG gọi MCP tiền/đơn/quảng cáo/đăng bài. KHÔNG tự tạo hay tự
bật loop khác. Mỗi vòng chỉ 1 cải tiến; ý tưởng thừa ghi vào note để vòng sau. Nếu không có gì
đáng làm -> ghi 'Không có cải tiến mới' và dừng.
"""


def ensure_meta_tools(root: str) -> dict:
    """Seed skill javis-builder + loop tự-cải-tiến vào brain (create-if-missing). Trả {created:[...]}."""
    root = Path(root)
    created = []
    try:
        sk = root / ".claude" / "skills" / "javis-builder" / "SKILL.md"
        if not sk.exists():
            sk.parent.mkdir(parents=True, exist_ok=True)
            sk.write_text(_SKILL_BUILDER, encoding="utf-8")
            created.append("skill:javis-builder")
    except Exception as e:
        print(f"[meta seed skill] {e}", file=__import__('sys').stderr)
    try:
        lp = root / "Javis" / "loops" / "tu-cai-tien-javis.md"
        if not lp.exists():
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_text(_LOOP_SELF_IMPROVE.format(today=_today()), encoding="utf-8")
            created.append("loop:tu-cai-tien-javis")
    except Exception as e:
        print(f"[meta seed loop] {e}", file=__import__('sys').stderr)
    return {"created": created}
