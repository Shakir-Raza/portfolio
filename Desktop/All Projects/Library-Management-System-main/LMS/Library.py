import tkinter as tk
from tkinter import messagebox
from collections import deque

# ── Design tokens ────────────────────────────────────────────────────────────
BG        = "#F7F6F3"
SURFACE   = "#FFFFFF"
BORDER    = "#E2E0DA"
TEXT      = "#1A1917"
MUTED     = "#78756E"
ACCENT    = "#2C2C2C"
ACCENT_FG = "#FFFFFF"
DANGER    = "#C0392B"
DANGER_FG = "#FFFFFF"
ENTRY_BG  = "#FFFFFF"
ENTRY_FG  = TEXT
FONT_HEAD = ("Georgia", 17, "bold")
FONT_BODY = ("Helvetica Neue", 10)
FONT_BTN  = ("Helvetica Neue", 10)
FONT_LBL  = ("Helvetica Neue", 10)

def style_root(root):
    root.configure(bg=BG)
def style_heading(widget):
    widget.configure(bg=BG, fg=TEXT, font=FONT_HEAD, pady=6)

def style_label(widget, muted=False):
    widget.configure(bg=BG, fg=MUTED if muted else TEXT, font=FONT_LBL)

def style_entry(widget):
    widget.configure(
        bg=ENTRY_BG, fg=ENTRY_FG,
        font=FONT_BODY,
        relief="flat",
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=TEXT,
        insertbackground=TEXT,
        width=28,
    )

def style_button(widget, variant="default"):
    base = dict(
        font=FONT_BTN,
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=0, pady=10,
    )
    if variant == "danger":
        widget.configure(bg=DANGER, fg=DANGER_FG,
                         activebackground="#96281B",
                         activeforeground=DANGER_FG, **base)
    elif variant == "ghost":
        widget.configure(bg=BG, fg=MUTED,
                         activebackground=BORDER,
                         activeforeground=TEXT, **base)
    else:
        widget.configure(bg=ACCENT, fg=ACCENT_FG,
                         activebackground="#444",
                         activeforeground=ACCENT_FG, **base)

def make_button(parent, text, command, variant="default"):
    """Button that fills a padded horizontal band — never stretches edge-to-edge."""
    btn = tk.Button(parent, text=text, command=command)
    style_button(btn, variant)
    btn.pack(fill="x", padx=48, pady=4)
    return btn

def divider(parent):
    tk.Frame(parent, height=1, bg=BORDER).pack(fill="x", padx=24, pady=6)

def spacer(parent, h=8):
    tk.Frame(parent, height=h, bg=BG).pack()

def nav_bar(parent, back_cmd):
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x")
    btn = tk.Button(bar, text="← Back", command=back_cmd,
                    bg=BG, fg=MUTED, relief="flat", bd=0,
                    font=("Helvetica Neue", 10), cursor="hand2",
                    activebackground=BORDER, activeforeground=TEXT,
                    padx=14, pady=10)
    btn.pack(side="left")
    tk.Frame(bar, height=1, bg=BORDER).pack(fill="x", side="bottom")

# ── Data classes ─────────────────────────────────────────────────────────────
class Library:
    def __init__(self):
        self.books = set()

    def addbook(self, book):
        self.books.add(book)

    def deletebook(self, book):
        if book in self.books:
            self.books.remove(book)
            return True
        return False

    def displaybook(self):
        return list(self.books)

    def sorted_book(self):
        return sorted(self.books)

    def borrowbook(self, book):
        return book in self.books


class Queue:
    def __init__(self):
        self.queue = deque()

    def enqueue(self, item):
        self.queue.append(item)

    def dequeue(self):
        if not self.is_empty():
            return self.queue.popleft()
        return None

    def queue_display(self):
        return list(self.queue)

    def is_empty(self):
        return len(self.queue) == 0


class TreeNode:
    def __init__(self, key):
        self.right = None
        self.left = None
        self.val = key


class BST:
    def __init__(self):
        self.root = None

    def insert(self, key):
        if self.root is None:
            self.root = TreeNode(key)
        else:
            self._insert(self.root, key)

    def _insert(self, current, key):
        if key < current.val:
            if current.left is None:
                current.left = TreeNode(key)
            else:
                self._insert(current.left, key)
        elif key > current.val:
            if current.right is None:
                current.right = TreeNode(key)
            else:
                self._insert(current.right, key)

    def searching(self, key):
        return self._searching(self.root, key)

    def _searching(self, current, key):
        if current is None or current.val == key:
            return current
        elif key < current.val:
            return self._searching(current.left, key)
        else:
            return self._searching(current.right, key)

    def inorder_traversing(self):
        return self._inorder_traversing(self.root, [])

    def _inorder_traversing(self, current, result):
        if current:
            self._inorder_traversing(current.left, result)
            result.append(current.val)
            self._inorder_traversing(current.right, result)
        return result


class LibrarySystem:
    def __init__(self):
        self.library = Library()
        self.waiting_users = Queue()
        self.borrowed_books = []
        self.users = {"Shakir": "123", "User": "User"}

        for book in ["b1", "b2", "b3", "b4", "b5", "b6"]:
            self.library.addbook(book)

    def login(self, username, password):
        if username in self.users and self.users[username] == password:
            return "librarian" if username == "Shakir" else "user"
        return None


# ── GUI ───────────────────────────────────────────────────────────────────────
class LibraryGUI:
    def __init__(self, root):
        self.root = root
        self.library_system = LibrarySystem()
        self.root.title("Library Management System")
        style_root(self.root)
        self.login_screen()

    def clear_screen(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    # ── Login ────────────────────────────────────────────────────────────────
    def login_screen(self):
        self.clear_screen()
        spacer(self.root, 36)

        lbl_title = tk.Label(self.root, text="Library Management\nSystem")
        style_heading(lbl_title)
        lbl_title.pack()

        lbl_sub = tk.Label(self.root, text="Sign in to continue")
        style_label(lbl_sub, muted=True)
        lbl_sub.pack()

        divider(self.root)
        spacer(self.root, 8)

        lbl_u = tk.Label(self.root, text="Username")
        style_label(lbl_u, muted=True)
        lbl_u.pack()
        spacer(self.root, 3)
        self.username_entry = tk.Entry(self.root)
        style_entry(self.username_entry)
        self.username_entry.pack()

        spacer(self.root, 12)
        lbl_p = tk.Label(self.root, text="Password")
        style_label(lbl_p, muted=True)
        lbl_p.pack()
        spacer(self.root, 3)
        self.password_entry = tk.Entry(self.root, show="*")
        style_entry(self.password_entry)
        self.password_entry.pack()

        spacer(self.root, 20)
        make_button(self.root, "Sign In", self.validate_login)
        spacer(self.root, 28)

    def validate_login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()
        user_type = self.library_system.login(username, password)
        if user_type == "librarian":
            self.librarian_menu()
        elif user_type == "user":
            self.user_menu()
        else:
            messagebox.showerror("Error", "Invalid username or password!")

    # ── Librarian menu ───────────────────────────────────────────────────────
    def librarian_menu(self):
        self.clear_screen()
        spacer(self.root, 24)

        lbl = tk.Label(self.root, text="Librarian Menu")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 4)

        make_button(self.root, "Add Book",       self.add_book_screen)
        make_button(self.root, "Delete Book",    self.delete_book_screen, "danger")
        make_button(self.root, "Display Books",  self.display_books)
        make_button(self.root, "Sorted Books",   self.display_sorted_books)
        make_button(self.root, "Waiting Users",  self.display_waiting_users)
        make_button(self.root, "Borrowed Books", self.display_borrowed_books)

        spacer(self.root, 8)
        divider(self.root)
        make_button(self.root, "Logout", self.login_screen, "ghost")
        spacer(self.root, 16)

    # ── User menu ────────────────────────────────────────────────────────────
    def user_menu(self):
        self.clear_screen()
        spacer(self.root, 24)

        lbl = tk.Label(self.root, text="User Menu")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 4)

        make_button(self.root, "Display Books", self.display_books)
        make_button(self.root, "Borrow Book",   self.borrow_book_screen)
        make_button(self.root, "Return Book",   self.return_book_screen)

        spacer(self.root, 8)
        divider(self.root)
        make_button(self.root, "Logout", self.login_screen, "ghost")
        spacer(self.root, 16)

    # ── Add book ─────────────────────────────────────────────────────────────
    def add_book_screen(self):
        self.clear_screen()
        nav_bar(self.root, self.librarian_menu)
        spacer(self.root, 16)

        lbl = tk.Label(self.root, text="Add Book")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 12)

        lbl_n = tk.Label(self.root, text="Book Name")
        style_label(lbl_n, muted=True)
        lbl_n.pack()
        spacer(self.root, 4)
        self.book_name_entry = tk.Entry(self.root)
        style_entry(self.book_name_entry)
        self.book_name_entry.pack()

        spacer(self.root, 20)
        make_button(self.root, "Add Book", self.add_book)
        spacer(self.root, 20)

    def add_book(self):
        book_name = self.book_name_entry.get().strip()
        if not book_name:
            messagebox.showerror("Error", "Book name cannot be empty!")
            return
        self.library_system.library.addbook(book_name)
        messagebox.showinfo("Success", f"Book '{book_name}' added!")
        self.librarian_menu()

    # ── Delete book ──────────────────────────────────────────────────────────
    def delete_book_screen(self):
        self.clear_screen()
        nav_bar(self.root, self.librarian_menu)
        spacer(self.root, 16)

        lbl = tk.Label(self.root, text="Delete Book")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 12)

        lbl_n = tk.Label(self.root, text="Book Name")
        style_label(lbl_n, muted=True)
        lbl_n.pack()
        spacer(self.root, 4)
        self.book_name_entry = tk.Entry(self.root)
        style_entry(self.book_name_entry)
        self.book_name_entry.pack()

        spacer(self.root, 20)
        make_button(self.root, "Delete Book", self.delete_book, "danger")
        spacer(self.root, 20)

    def delete_book(self):
        book_name = self.book_name_entry.get().strip()
        if not book_name:
            messagebox.showerror("Error", "Book name cannot be empty!")
            return
        if self.library_system.library.deletebook(book_name):
            messagebox.showinfo("Success", f"Book '{book_name}' deleted!")
        else:
            messagebox.showerror("Error", f"Book '{book_name}' not found!")
        self.librarian_menu()

    # ── Display books ────────────────────────────────────────────────────────
    def display_books(self):
        self.clear_screen()
        nav_bar(self.root, self.librarian_menu)
        spacer(self.root, 16)

        lbl = tk.Label(self.root, text="Books in Library")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 8)

        books = self.library_system.library.displaybook()
        if books:
            for book in books:
                row = tk.Label(self.root, text=f"  · {book}", anchor="w", width=30)
                style_label(row)
                row.pack(pady=2)
        else:
            empty = tk.Label(self.root, text="No books available")
            style_label(empty, muted=True)
            empty.pack()

        spacer(self.root, 20)

    # ── Sorted books ─────────────────────────────────────────────────────────
    def display_sorted_books(self):
        self.clear_screen()
        nav_bar(self.root, self.librarian_menu)
        spacer(self.root, 16)

        lbl = tk.Label(self.root, text="Sorted Books")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 8)

        sorted_books = self.library_system.library.sorted_book()
        if sorted_books:
            for book in sorted_books:
                row = tk.Label(self.root, text=f"  · {book}", anchor="w", width=30)
                style_label(row)
                row.pack(pady=2)
        else:
            empty = tk.Label(self.root, text="No books available")
            style_label(empty, muted=True)
            empty.pack()

        spacer(self.root, 20)

    # ── Borrow book ──────────────────────────────────────────────────────────
    def borrow_book_screen(self):
        self.clear_screen()
        nav_bar(self.root, self.user_menu)
        spacer(self.root, 16)

        lbl = tk.Label(self.root, text="Borrow Book")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 12)

        lbl_n = tk.Label(self.root, text="Book Name")
        style_label(lbl_n, muted=True)
        lbl_n.pack()
        spacer(self.root, 4)
        self.book_name_entry = tk.Entry(self.root)
        style_entry(self.book_name_entry)
        self.book_name_entry.pack()

        spacer(self.root, 20)
        make_button(self.root, "Borrow Book", self.borrow_book)
        spacer(self.root, 20)

    def borrow_book(self):
        book_name = self.book_name_entry.get().strip()
        if not book_name:
            messagebox.showerror("Error", "Book name cannot be empty!")
            return
        if self.library_system.library.borrowbook(book_name):
            self.library_system.library.deletebook(book_name)
            self.library_system.borrowed_books.append(book_name)
            messagebox.showinfo("Success", f"You borrowed '{book_name}'!")
        else:
            messagebox.showerror("Error", f"Book '{book_name}' not available!")
        self.user_menu()

    # ── Return book ──────────────────────────────────────────────────────────
    def return_book_screen(self):
        self.clear_screen()
        nav_bar(self.root, self.user_menu)
        spacer(self.root, 16)

        lbl = tk.Label(self.root, text="Return Book")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 12)

        lbl_n = tk.Label(self.root, text="Book Name")
        style_label(lbl_n, muted=True)
        lbl_n.pack()
        spacer(self.root, 4)
        self.book_name_entry = tk.Entry(self.root)
        style_entry(self.book_name_entry)
        self.book_name_entry.pack()

        spacer(self.root, 20)
        make_button(self.root, "Return Book", self.return_book)
        spacer(self.root, 20)

    def return_book(self):
        book_name = self.book_name_entry.get().strip()
        if not book_name:
            messagebox.showerror("Error", "Book name cannot be empty!")
            return
        if book_name in self.library_system.borrowed_books:
            self.library_system.borrowed_books.remove(book_name)
            self.library_system.library.addbook(book_name)
            messagebox.showinfo("Success", f"Book '{book_name}' returned!")
        else:
            messagebox.showerror("Error", f"Book '{book_name}' not found in borrowed books!")
        self.user_menu()

    # ── Waiting users ────────────────────────────────────────────────────────
    def display_waiting_users(self):
        self.clear_screen()
        nav_bar(self.root, self.librarian_menu)
        spacer(self.root, 16)

        lbl = tk.Label(self.root, text="Waiting Users")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 8)

        waiting_users = self.library_system.waiting_users.queue_display()
        if waiting_users:
            for user in waiting_users:
                row = tk.Label(self.root, text=f"  · {user}", anchor="w", width=30)
                style_label(row)
                row.pack(pady=2)
        else:
            empty = tk.Label(self.root, text="No waiting users")
            style_label(empty, muted=True)
            empty.pack()

        spacer(self.root, 20)

    # ── Borrowed books ───────────────────────────────────────────────────────
    def display_borrowed_books(self):
        self.clear_screen()
        nav_bar(self.root, self.librarian_menu)
        spacer(self.root, 16)

        lbl = tk.Label(self.root, text="Borrowed Books")
        style_heading(lbl)
        lbl.pack()

        divider(self.root)
        spacer(self.root, 8)

        borrowed_books = self.library_system.borrowed_books
        if borrowed_books:
            for book in borrowed_books:
                row = tk.Label(self.root, text=f"  · {book}", anchor="w", width=30)
                style_label(row)
                row.pack(pady=2)
        else:
            empty = tk.Label(self.root, text="No borrowed books")
            style_label(empty, muted=True)
            empty.pack()

        spacer(self.root, 20)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    gui = LibraryGUI(root)
    root.mainloop()
