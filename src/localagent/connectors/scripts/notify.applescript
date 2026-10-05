-- argv: title, message, subtitle
on run argv
	display notification (item 2 of argv) with title (item 1 of argv) subtitle (item 3 of argv)
	return "ok"
end run
