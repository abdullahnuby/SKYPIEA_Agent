# مهارات Markdown

أي مجلد فيه `SKILL.md` هنا بيتحمّل تلقائيًا. التغييرات بتتقرأ من غير إعادة تشغيل.

## الصيغة

```markdown
---
name: example
description: وصف قصير
trigger: "الجملة الأولى|الجملة التانية|re:^regex.*$"
reply: "الرد الثابت"
fast_path: true
---
```

مهارة تنفّذ أداة:

```markdown
---
name: youtube
trigger: "افتح يوتيوب|youtube"
tool: open_target
args: {"target": "youtube"}
---
```

- `trigger`: نص عادي أو regex لو بدأ بـ `re:`. استخدم `|` للفصل.
- `reply`: رد ثابت. يدعم `{match}` للنص كله.
- `tool` + `args`: تنفيذ أداة من `agent/tools/`. يدعم `{match}` و`{1}`.
- `fast_path`: محفوظ للتوافق مع Ethan؛ حاليًا كل المهارات سريعة.

## أدوات متاحة

شوف `/tools` في تيليجرام.
