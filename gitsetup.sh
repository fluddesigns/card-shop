cd ~/card-shop

# 1. Initialize Git
git init

# 2. Configure your identity (required for commits)
git config user.email "you@example.com"
git config user.name "CardShop Admin"

# 3. Add files (The .gitignore will prevent DB/Env from being added)
git add .

# 4. Commit the current stable state
git commit -m "Initial release: Multi-tenant MVP"

# 5. Rename branch to main
git branch -M main

### Step 3: Create a GitHub Repository
1.  Go to [GitHub.com](https://github.com) and log in.
2.  Click **New Repository**.
3.  Name it `card-shop`.
4.  **Important:** Select **Private**.
5.  Click **Create repository**.
6.  Copy the HTTPS URL (e.g., `https://github.com/YourUser/card-shop.git`).

### Step 4: Link Server to GitHub
Back on your **Server**:

```bash
# Replace URL with your actual GitHub URL
git remote add origin https://github.com/YourUser/card-shop.git

# Push the code
git push -u origin main
*(It will ask for your GitHub username and password. Note: For password, you must use a Personal Access Token if you have 2FA enabled, which is standard now).*

---

### Step 5: How to Develop New Features (The New Routine)

Now that the link is established, here is how you add the **Real Images** feature without breaking the server.

**1. On your Workstation (Laptop/Desktop):**
* Clone the repo: `git clone https://github.com/YourUser/card-shop.git`
* Create a folder `card-shop` on your computer.
* **Create the `.env` file manually** on your computer (since we ignored it) if you want to run it locally for testing.

**2. Make Changes:**
* Edit `app.py` to add the Scryfall API logic.
* Edit `binder.html` to add the image tags.

**3. Push Changes:**
```bash
git add .
git commit -m "Added Scryfall image integration"
git push origin main

**4. Deploy on Server:**
SSH into your server and run:
```bash
cd ~/card-shop
git pull origin main
docker compose down
docker compose up -d --build

### Next Steps?
Once you have confirmed you have pushed your code to GitHub successfully, I can give you the **Git-ready code snippet** for the Scryfall Image integration. You will apply it on your workstation, push it, and watch your server update gracefully.

**Are you ready for the Scryfall Image code?**
