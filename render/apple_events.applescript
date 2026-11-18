on cleanText(t)
	set AppleScript's text item delimiters to {linefeed, return, tab}
	set parts to text items of (t as string)
	set AppleScript's text item delimiters to " "
	set t2 to parts as string
	set AppleScript's text item delimiters to ""
	return t2
end cleanText

on fmt(d)
	set y to year of d as string
	set m to text -2 thru -1 of ("0" & (month of d as integer))
	set dd to text -2 thru -1 of ("0" & (day of d))
	set hh to text -2 thru -1 of ("0" & (hours of d))
	set mm to text -2 thru -1 of ("0" & (minutes of d))
	return y & "-" & m & "-" & dd & " " & hh & ":" & mm
end fmt

tell application "Calendar"
	set todayStart to (current date)
	set time of todayStart to 0
	set rangeEnd to todayStart + (2 * days)
	set output to ""
	repeat with cal in calendars
		set evs to (every event of cal whose start date ≥ todayStart and start date < rangeEnd)
		repeat with ev in evs
			set output to output & my fmt(start date of ev) & tab & my fmt(end date of ev) & tab & (allday event of ev) & tab & my cleanText(name of cal) & tab & my cleanText(summary of ev) & linefeed
		end repeat
	end repeat
	return output
end tell
