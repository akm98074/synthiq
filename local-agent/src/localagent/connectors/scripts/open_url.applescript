-- argv: url (e.g. whatsapp://send?phone=...&text=...). Opens it with the default handler.
on run argv
	open location (item 1 of argv)
	return "opened"
end run
