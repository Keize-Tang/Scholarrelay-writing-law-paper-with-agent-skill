# 发布到 GitHub · 零基础操作指南

> 面向从没上传过代码的人。全程**不需要命令行**、**不需要 Git**，用鼠标拖拽即可完成。
> 预计耗时：10 分钟。

---

## 第 0 步：先确认包里有什么

打开文件夹 `scholarrelay`，你应该看到这些内容：

```
scholarrelay/
├── .gitignore      ← 隐藏文件，见下方说明
├── LICENSE
├── README.md       ← 别人打开仓库第一眼看到的东西
├── SKILL.md
├── assets/         （5 个模板）
├── docs/           （本指南）
├── references/     （9 个规范文档）
└── scripts/        （5 个脚本）
```

### ⚠️ 关于 `.gitignore`（隐藏文件）

Windows 默认**不显示**以点开头的文件。上传前请先让它可见：

- 打开文件夹 → 顶部「查看」→ 勾选「显示」→「隐藏的项目」

如果懒得弄，**跳过 `.gitignore` 也能上传成功**，只是以后仓库里可能混入临时文件。不影响使用。

---

## 第 1 步：在 GitHub 建一个空仓库

1. 打开 [https://github.com](https://github.com) 并登录你的账号。
2. 点右上角 **「+」** → **「New repository」**。

   （也可以直接访问 [https://github.com/new](https://github.com/new)）

3. 填写：

   | 字段 | 填什么 |
   |---|---|
   | **Repository name** | `scholarrelay` |
   | **Description** | `人机协作学术论文写作工作流：8 阶段协议 + 文献分级 + 编号校验 + 期刊体例排版` |
   | **Public / Private** | 选 **Public**（公开，别人才看得到、能搜到） |

4. ⚠️ **下面三个勾选框全部不要勾**：
   - ❌ Add a README file
   - ❌ Add .gitignore
   - ❌ Choose a license

   因为我们的包里**已经有** README 和 LICENSE 了，勾了会冲突。

5. 点绿色按钮 **「Create repository」**。

页面会跳转到一个"空仓库"页面，上面写着 *Quick setup — if you've done this kind of thing before*。

---

## 第 2 步：把文件拖上去

1. 在空仓库页面，找到一行蓝色链接：**「uploading an existing file」**（或页面上方的 **「Add file」→「Upload files」**），点它。

2. 打开你电脑上的 `scholarrelay` 文件夹，**全选里面的所有内容**
   （`Ctrl + A`）——注意是选**文件夹里面的东西**，不要选文件夹本身。

   要选中的应该是：
   `.gitignore`、`LICENSE`、`README.md`、`SKILL.md` 以及 `assets`、`docs`、`references`、`scripts` 四个文件夹。

3. 把这些内容**拖进浏览器的虚线框**里。

4. 等页面下方出现文件列表，确认能看到 `SKILL.md`、`README.md`、
   以及 `references/00-workflow-overview.md` 这类带路径的文件（说明文件夹结构被保留了）。

   > ⚠️ 如果看不到子文件夹里的文件，只看到 4 个文件夹名，也没关系——GitHub 会正确保留结构。
   > 但要确认**没有多出一层** `scholarrelay/` 目录。

5. 拉到页面最下方，在 **Commit changes** 的输入框里写一句说明：

   ```
   feat: 首次发布人机协作论文写作工作流
   ```

6. 点 **「Commit changes」**。

**完成！** 仓库首页现在应该自动渲染出 README 的内容。

---

## 第 3 步：给仓库"装修"一下（可选但推荐）

### 加标签（Topics）

仓库首页右上角点 ⚙️ 齿轮图标（**About** 区域），填写：

- **Description**：同上
- **Topics**（标签，逐个输入后回车）：

  ```
  paper-writing  academic-writing  law  citation
  ai-agent  skill  workflow  cnki  gbt7714  python
  ```

- 勾选 **Releases / Packages 不用管**，点 **Save changes**。

### 确认 README 显示正常

回到仓库首页，检查：

- [ ] 标题、徽章、流程图正常显示（GitHub 会自动渲染 Mermaid）
- [ ] 目录结构那段代码块没有乱码
- [ ] 中文没有出现问号或方框

---

## 第 4 步：以后怎么更新文件

有两种方式，都很简单。

### 方式 A：改单个文件（最常用）

1. 在仓库里点进那个文件（例如 `scripts/validate.py`）
2. 点右上角的 ✏️ **铅笔图标**
3. 直接改，改完拉到下面点 **Commit changes**

### 方式 B：整体替换 / 新增多个文件

1. 仓库页面 **「Add file」→「Upload files」**
2. 拖入新文件（同名文件会被覆盖，GitHub 会在 Commit 时显示"删除+新增"）
3. 写说明 → **Commit changes**

> 💡 每次修改都建议写清楚 Commit 说明，例如
> `fix: 修正 renumber.py 未生效的 --drop-uncited`
> 这样别人（和未来的你）能看出改了什么。

---

## 常见问题

### Q1：上传时报 "Yowza, that's a big file"

单个文件不能超过 25MB（网页上传的上限）。我们的包很小，一般不会遇到。
如果真的遇到，检查是不是误把下载的 PDF 或 `__pycache__` 拖进去了——这两类都已写进 `.gitignore`。

### Q2：中文文件名显示成乱码

GitHub 对中文文件名支持没问题，但**URL 里会变成百分号编码**，这是正常的。
如果本地提交时（方式 B 用命令行）出现乱码，改用网页上传即可避免。

### Q3：脚本在别人电脑上跑不起来

`parse_cnki.py` / `cnki2gbt.py` / `validate.py` / `renumber.py` **只用 Python 标准库**，
装了 Python 3.9+ 就能跑。

`md2docx.py` 需要额外装一个包：

```bash
pip install python-docx
```

建议在 README 里已经写明这一点（本仓库已写）。

### Q4：想改作者名 / 版权声明

打开 `LICENSE`，把 `Copyright (c) 2026 <作者>` 改成你的名字或 GitHub 用户名。

> ⚠️ **建议用昵称或 GitHub 用户名，不要写「真实姓名 + 学校 + 学院」。**
> 三者组合会直接定位到个人。发布前请先跑一遍隐私扫描：
> `python scripts/check_pii.py .`（详见 `references/16-privacy-protection.md`）

### Q5：仓库建错了，想删掉重建

仓库页面 → **Settings** → 拉到最底部 **Danger Zone** → **Delete this repository**。
删除前需要输入仓库名确认。删除后可以按本指南重新来一遍。

### Q6：怎么知道有没有人下载我的项目

仓库首页 **Insights → Traffic** 可以看访问量、克隆次数、来源。
项目被人 Star（收藏）时 GitHub 会发邮件通知你。

---

## 进阶（等你用顺了再看）

### 用命令行管理（可选）

装了 [Git](https://git-scm.com/downloads) 之后：

```bash
cd scholarrelay

git init
git add .
git commit -m "feat: 首次发布人机协作论文写作工作流"
git branch -M main
git remote add origin https://github.com/<你的用户名>/scholarrelay.git
git push -u origin main
```

以后再改文件，只需三条命令：

```bash
git add .
git commit -m "fix: 说明改了什么"
git push
```

### 发布版本（Release）

当你觉得这套工作流稳定了，可以在仓库右侧 **Releases → Create a new release**，
填一个版本号（如 `v1.0.0`），GitHub 会自动打包 zip 供人下载。这也是别人推荐你项目的加分项。

### 让别人能"一键安装"成 AI 技能

如果这个仓库要作为 AI Agent 技能分发，通常的做法是把仓库地址贴到对方的技能安装入口，
或让使用者手动把文件夹放进技能目录。`SKILL.md` 的 frontmatter 就是给 Agent 读的入口，
**不要改动它的 `name` 和 `description` 字段格式**。

---

## 上传前终极自检清单

- [ ] 仓库名 `scholarrelay`
- [ ] 可见性 **Public**
- [ ] 创建时**没有**勾选 README / .gitignore / license（避免冲突）
- [ ] 拖入的是文件夹**内部的内容**，没有多套一层目录
- [ ] 首页能正确渲染 README（标题、徽章、Mermaid 流程图）
- [ ] `references/`、`assets/`、`scripts/` 三个子文件夹都在，且里面有文件
- [ ] `LICENSE` 里的作者名已改成你自己的
- [ ] 没有上传 PDF、`CNKI-*.txt`、`__pycache__`、`*.docx` 等无关文件
- [ ] Commit 说明写清楚了这次改了什么
