; NES Radar on a nesp32: the airport and its aircraft over nesp32's link.
;
; The source includes this at the end of CODE and sends the editor's Start
; here (radar_submit); everything it draws with, and every check of a
; record, is in nes_radar_scope_v3.s.
;
; The link is nesp32's (its nes/lib/nesp.inc and docs/PROTOCOL.md): one
; firmware on the nesp32 serves every ROM, and this one asks it for the
; RADAR service. Every use of the link is one exchange: a request goes out,
; and one reply comes back or does not. So nothing here waits on the line,
; and nothing of nes-radar's timing is left: no chunks, no window in which
; the host keeps quiet, no pause to ask for. The scope is a loop that goes
; round once a frame, and makes at most one exchange each time.
;
; nes-radar keeps its NMI off but for the moment it waits for a vblank to
; write in, and so does this. An exchange is made with it off, just after
; such a write, and the receiver gives up by counting (link.inc is made
; with --timeout).
;
;   AIRPORT    an id and the four letters. The same request is both "this
;              airport" and "how does it stand", so it is sent until the
;              nesp32 has found where the airport is, which it asks the
;              Internet, and again whenever it has forgotten it.
;   SCENE      twice a second: the scene the console has, by its serial.
;              The reply has the aircraft only if they are others.
;   LAST       once, before the editor: the letters of the last airport
;              the nesp32 found, which it keeps over power-off. The
;              editor begins with them in place of nes-radar's KSBA.
;   IDENTITY   a slot's names, one a frame, when a scene's reply says the
;              names are not the ones the console has. They are fetched
;              before the scene they belong to is taken, as nes-radar's
;              server sends them before it.
;
; The nesp32 knows this ROM by its hello, which goes out before the first
; airport and again whenever the nesp32 says it has no such service in use:
; it was switched off and on.

OUT0_MARK = $01

NESP_RX_MASK = $7F              ; a scene's reply is 78 bytes
NESP_TX_MAX  = 8                ; the hello: 7 bytes and one service
NESP_CRC_TABLE = 1              ; 35 cycles a byte: a scene's exchange and what
                                ; is made of it fit in a frame
NESP_TIMEOUT = 2                ; passes of 4.15 ms waited for a reply
NESP_NMI_ONLY = 1               ; no exchange is made with the NMI on
.define NESP_APP "RADR"
NESP_APP_VERSION = 1

.include "nesp.inc"

; RADAR's replies. To SCENE: the state, the airport's id, the scene's
; serial and the names', and with a scene the console has not, its flags,
; how many aircraft, and nine bytes of each. To IDENTITY: the state, the
; id, the names' serial and a slot's record.
REPLY_STATE   = nesp_reply
REPLY_ID      = nesp_reply + 1
SCENE_SERIAL  = nesp_reply + 2
SCENE_NAMES   = nesp_reply + 3
SCENE_FLAGS   = nesp_reply + 4
SCENE_COUNT   = nesp_reply + 5
SCENE_RECORDS = nesp_reply + 6
SCENE_HEAD    = 6
SCENE_BRIEF   = 4               ; a reply with no scene in it
NAMES_SERIAL  = nesp_reply + 2
NAMES_RECORD  = nesp_reply + 3
NAMES_HEAD    = 3

.assert MAX_TARGETS = NESP_RADAR_TARGETS_MAX, error, "a scene is as many aircraft as the nesp32 sends"
.assert RECORD_SIZE = NESP_RADAR_MOTION_LEN, error, "an aircraft is as long as the nesp32 sends it"
.assert IDENTITY_RECORD_SIZE = NESP_RADAR_NAMES_LEN, error, "and so are its names"
.assert SCENE_STALE = NESP_SCENE_STALE, error, "the scene's flags are RADAR's"
.assert SCENE_SEVERE = NESP_SCENE_DOWN | NESP_SCENE_BAD_DATA | NESP_SCENE_BAD_PLACE, error, "the scene's flags are RADAR's"
.assert SCENE_HEAD + MAX_TARGETS * RECORD_SIZE <= NESP_RX_MASK, error, "a scene must fit its buffer"

POLL_FRAMES   = 30              ; between one SCENE and the next
MISS_LIMIT    = 8               ; exchanges in a row unanswered before the scope says so
ANSWER_FRAMES = 120             ; and frames the editor waits for a nesp32
RECALL_FRAMES = 8               ; and the splash, for the airport it kept

; What radar_open made of its exchange. The ones under $80 are why there
; will be no scope, and the editor's startup_error: 1 is nes-radar's own
; INVALID AIRPORT.
OPEN_INVALID = 1
OPEN_SILENT  = 2                ; no answer
OPEN_NO_WIFI = 3
OPEN_UPDATE  = 4                ; a firmware with no RADAR, or another protocol
OPEN_LOOKUP  = 5                ; where the airport is could not be asked
OPEN_AGAIN   = $80              ; so far so good: there is more to ask
OPEN_DONE    = $81              ; the nesp32 has the airport


.segment "ZEROPAGE"
radar_id:         .res 1        ; which choice of airport this is: a new one, a new id
radar_greeted:    .res 1        ; the nesp32 has answered this ROM's hello
radar_chosen:     .res 1        ; and has the airport
radar_have:       .res 1        ; the serial of the scene on the screen; 0 for none
radar_names_have: .res 1        ; and of the names
radar_names_want: .res 1        ; the names being fetched
radar_slot:       .res 1        ; the next of them to ask for; MAX_TARGETS when none are
radar_wait:       .res 1        ; frames to the next SCENE
radar_misses:     .res 1        ; exchanges in a row with no answer
radar_tries:      .res 1

.segment "RODATA"
; The editor's messages, sixteen characters as nes-radar's own are.
radar_messages:
    ; NO NESP32 ANSWER
    .byte CHAR_A+('N'-'A'),CHAR_A+('O'-'A'),CHAR_SPACE
    .byte CHAR_A+('N'-'A'),CHAR_A+('E'-'A'),CHAR_A+('S'-'A'),CHAR_A+('P'-'A'),CHAR_0+3,CHAR_0+2,CHAR_SPACE
    .byte CHAR_A+('A'-'A'),CHAR_A+('N'-'A'),CHAR_A+('S'-'A'),CHAR_A+('W'-'A'),CHAR_A+('E'-'A'),CHAR_A+('R'-'A')
    ; NESP32 NO WI-FI
    .byte CHAR_A+('N'-'A'),CHAR_A+('E'-'A'),CHAR_A+('S'-'A'),CHAR_A+('P'-'A'),CHAR_0+3,CHAR_0+2,CHAR_SPACE
    .byte CHAR_A+('N'-'A'),CHAR_A+('O'-'A'),CHAR_SPACE
    .byte CHAR_A+('W'-'A'),CHAR_A+('I'-'A'),CHAR_HYPHEN,CHAR_A+('F'-'A'),CHAR_A+('I'-'A'),CHAR_SPACE
    ; UPDATE NESP32
    .byte CHAR_SPACE
    .byte CHAR_A+('U'-'A'),CHAR_A+('P'-'A'),CHAR_A+('D'-'A'),CHAR_A+('A'-'A'),CHAR_A+('T'-'A'),CHAR_A+('E'-'A'),CHAR_SPACE
    .byte CHAR_A+('N'-'A'),CHAR_A+('E'-'A'),CHAR_A+('S'-'A'),CHAR_A+('P'-'A'),CHAR_0+3,CHAR_0+2
    .byte CHAR_SPACE,CHAR_SPACE
    ; LOOKUP FAILED
    .byte CHAR_SPACE
    .byte CHAR_A+('L'-'A'),CHAR_A+('O'-'A'),CHAR_A+('O'-'A'),CHAR_A+('K'-'A'),CHAR_A+('U'-'A'),CHAR_A+('P'-'A'),CHAR_SPACE
    .byte CHAR_A+('F'-'A'),CHAR_A+('A'-'A'),CHAR_A+('I'-'A'),CHAR_A+('L'-'A'),CHAR_A+('E'-'A'),CHAR_A+('D'-'A')
    .byte CHAR_SPACE,CHAR_SPACE
.assert * - radar_messages = 4 * 16, error, "a message is sixteen characters"

.segment "CODE"

; Before the editor is first shown: the letters of the airport the nesp32
; kept, into icao_code. With no nesp32, or one that kept none, they stay as
; they are; the wait for one is RECALL_FRAMES at the most.
.proc radar_recall
    lda #RECALL_FRAMES
    sta radar_tries
@try:
    jsr wait_vblank
    lda radar_greeted
    bne @ask
    lda #NESP_SVC_RADAR
    sta nesp_request + NESP_HELLO_FIXED
    ldy #1
    jsr nesp_hello
    bcs @silent
    cmp #NESP_ST_OK
    bne @done                   ; a firmware with no RADAR: Start will say so
    inc radar_greeted
    bne @try
@ask:
    lda #NESP_SVC_RADAR
    ldx #NESP_RADAR_LAST
    ldy #0
    jsr nesp_call
    bcs @silent
    cmp #NESP_ST_OK
    bne @done
    lda nesp_reply_len
    cmp #4
    bne @done                   ; it has kept none
    ldx #3
@check:
    lda nesp_reply,x
    cmp #'A'
    bcc @done
    cmp #'Z' + 1
    bcs @done
    dex
    bpl @check
    ldx #3
@letter:
    lda nesp_reply,x
    sta icao_code,x
    dex
    bpl @letter
@done:
    rts
@silent:
    dec radar_tries
    bne @try
    rts
.endproc

; The editor's Start: ask the nesp32 for the airport in icao_code, and go
; to the scope if it knows it, or back to the editor with the reason.
.proc radar_submit
    lda #0
    jsr show_startup_message    ; REQUESTING
    inc radar_id
    lda #0
    sta radar_chosen
    sta startup_error           ; whatever kept the last one from the scope
    lda #ANSWER_FRAMES
    sta radar_tries
@try:
    jsr wait_vblank
    jsr radar_open
    cmp #OPEN_DONE
    beq radar_scope
    cmp #OPEN_AGAIN
    beq @try
    cmp #OPEN_SILENT
    bne @refused
    dec radar_tries
    bne @try
@refused:
    sta startup_error
    jmp reset::radar_editor
.endproc

; The scope: once round a frame. The pad, the link's age, at most one
; exchange, and the targets drawn again with the next of them in front, so
; that more than four on a line take turns to be seen.
.proc radar_scope
    jsr initialize_display_buffers
    jsr initialize_video
    lda #1
    sta radar_chosen
    jsr radar_begin
@frame:
    jsr update_selection        ; B asks for the editor
    lda navigation_requested
    bne @leave
    jsr age_link
    bcc :+
    jsr commit_display          ; ten seconds with nothing: WAITING
:
    jsr radar_poll
    lda startup_error           ; the nesp32 no longer has the airport, and why
    bne @leave

    lda displayed_count
    sta packet_count
    jsr build_oam_shadow
    jsr tick_link_dots
    bcc :+
    lda #1
    sta link_dirty
:
    lda selected_slot
    cmp previous_selected_slot
    beq @oam_only
    jsr build_selected_fields
    jsr commit_selection
    jmp @advance
@oam_only:
    lda link_dirty              ; the dots go with the OAM, not with a selection
    beq :+
    lda #0
    sta link_dirty
    jsr commit_oam_link
    jmp @advance
:
    jsr commit_oam
@advance:
    inc oam_rotation
    lda oam_rotation
    and #7
    sta oam_rotation
    jmp @frame

@leave:
    lda #0
    sta navigation_requested
    sta active_slots
    sta controller_pending
    jmp reset::radar_editor
.endproc

; The targets' turn in front and the LINK field's dots, in one vblank: the
; OAM DMA's 520 cycles and nine tiles of the field.
.proc commit_oam_link
    jsr begin_vram_update
    lda #0
    sta OAMADDR
    lda #>oam_shadow
    sta OAMDMA
    jmp write_link_during_vblank
.endproc

; Nothing on the screen is the nesp32's yet: ask for the scene at once.
.proc radar_begin
    lda #0
    sta radar_have
    sta radar_names_have
    sta radar_misses
    lda #MAX_TARGETS
    sta radar_slot
    lda #1
    sta radar_wait
    rts
.endproc

; One exchange towards a nesp32 that has the airport: the hello if it has
; not had one, and then the airport. Returns OPEN_* in A.
.proc radar_open
    lda radar_greeted
    bne @choose
    lda #NESP_SVC_RADAR
    sta nesp_request + NESP_HELLO_FIXED
    ldy #1
    jsr nesp_hello
    bcs @silent
    cmp #NESP_ST_OK
    bne @update
    inc radar_greeted
@again:
    lda #OPEN_AGAIN
    rts

@choose:
    lda radar_id
    sta nesp_request
    ldx #3
@letter:
    lda icao_code,x
    sta nesp_request + 1,x
    dex
    bpl @letter
    lda #NESP_SVC_RADAR
    ldx #NESP_RADAR_AIRPORT
    ldy #5
    jsr nesp_call
    bcs @silent
    cmp #NESP_ST_OK
    beq @heard
    cmp #NESP_ST_INACTIVE
    bne @update
    lda #0                      ; it has forgotten the hello: say it again
    sta radar_greeted
    beq @again
@heard:
    lda REPLY_ID                ; about this choice, or an older one?
    cmp radar_id
    bne @again
    lda REPLY_STATE
    cmp #NESP_SCOPE_IDLE
    beq @again
    cmp #NESP_SCOPE_LOOKING     ; it is asking where the airport is
    beq @again
    cmp #NESP_SCOPE_NOT_FOUND
    beq @invalid
    cmp #NESP_SCOPE_NO_WIFI
    beq @no_wifi
    cmp #NESP_SCOPE_NO_LOOKUP
    beq @no_lookup
    lda #OPEN_DONE
    rts
@no_lookup:
    lda #OPEN_LOOKUP
    rts
@silent:
    lda #OPEN_SILENT
    rts
@update:
    lda #OPEN_UPDATE
    rts
@invalid:
    lda #OPEN_INVALID
    rts
@no_wifi:
    lda #OPEN_NO_WIFI
    rts
.endproc

; The scope's exchange for this frame, if it is time for one.
.proc radar_poll
    lda radar_chosen
    bne @running
    ; The nesp32 has forgotten the airport, or this ROM: tell it again.
    jsr radar_open
    cmp #OPEN_AGAIN
    beq @done
    cmp #OPEN_SILENT
    beq @missed
    cmp #OPEN_DONE
    beq @chosen
    cmp #OPEN_NO_WIFI           ; it has the airport, and will have its Wi-Fi back
    beq @chosen
    sta startup_error
@done:
    rts
@missed:
    jmp radar_missed
@chosen:
    lda #1
    sta radar_chosen
    jmp radar_begin

@running:
    lda radar_slot
    cmp #MAX_TARGETS
    bcc @names
    dec radar_wait
    bne @done
    lda #POLL_FRAMES
    sta radar_wait
    lda radar_id
    sta nesp_request
    lda radar_have
    sta nesp_request + 1
    lda #NESP_SVC_RADAR
    ldx #NESP_RADAR_SCENE
    ldy #2
    jsr nesp_call
    jsr radar_heard
    bcs @done
    cmp #NESP_SCOPE_READY       ; no scene yet, or no Wi-Fi: the link's age says so
    bne radar_placeless
    jsr note_valid_packet
    lda nesp_reply_len
    cmp #SCENE_BRIEF
    beq @done                   ; the scene on the screen is the one it has
    lda SCENE_NAMES
    cmp radar_names_have
    beq @take
    sta radar_names_want        ; the names first, and then this scene again
    lda #0
    sta radar_slot
    jmp note_link_stream
@take:
    jmp radar_take

@names:
    lda radar_id
    sta nesp_request
    lda radar_slot
    sta nesp_request + 1
    lda #NESP_SVC_RADAR
    ldx #NESP_RADAR_IDENTITY
    ldy #2
    jsr nesp_call
    jsr radar_heard
    bcs @named
    cmp #NESP_SCOPE_READY
    bne @no_names
    lda nesp_reply_len
    cmp #NAMES_HEAD + IDENTITY_RECORD_SIZE
    bne @bad_names
    lda NAMES_SERIAL
    cmp radar_names_want
    beq @same
    sta radar_names_want        ; they have changed meanwhile: from the first again
    lda #0
    sta radar_slot
    rts
@same:
    jsr radar_names
    bcs @bad_names
    inc radar_slot
    lda radar_slot
    cmp #MAX_TARGETS
    bne @named
    lda radar_names_want
    sta radar_names_have
    jsr build_selected_identity
    lda #1                      ; and now the scene they are the names of
    sta radar_wait
@named:
    rts
@bad_names:
    lda #<link_bad_data_chars   ; an aircraft or a name that cannot be shown
    ldx #>link_bad_data_chars
    jsr show_link
@no_names:
    lda #MAX_TARGETS
    sta radar_slot
    rts
.endproc

; A state that is not READY: nothing to do, unless it is that the airport
; the nesp32 was told of again has turned out to be nowhere. Then the
; editor says so.
.proc radar_placeless
    cmp #NESP_SCOPE_NOT_FOUND
    bne :+
    lda #OPEN_INVALID
    sta startup_error
:
    cmp #NESP_SCOPE_NO_LOOKUP
    bne :+
    lda #OPEN_LOOKUP
    sta startup_error
:
    rts
.endproc

; After an exchange, with what nesp_call returned. Carry clear and A = the
; state if the reply is about this airport; carry set if there is nothing
; to be made of it.
.proc radar_heard
    bcs radar_missed
    cmp #NESP_ST_OK
    bne @refused
    lda #0
    sta radar_misses
    lda REPLY_STATE
    cmp #NESP_SCOPE_IDLE        ; not the airport it has: choose it again
    beq @forgotten
    clc
    rts
@refused:                       ; it was switched off and on: hello again
    lda #0
    sta radar_greeted
@forgotten:
    lda #0
    sta radar_chosen
    sec
    rts
.endproc

; No answer. The scope says so once MISS_LIMIT in a row have gone by, and
; when an answer comes again, takes the scene afresh to say that instead.
.proc radar_missed
    lda radar_misses
    cmp #MISS_LIMIT
    bcs @done
    inc radar_misses
    lda radar_misses
    cmp #MISS_LIMIT
    bne @done
    lda #0
    sta radar_have
    lda #<link_no_answer_chars
    ldx #>link_no_answer_chars
    jsr show_link
@done:
    sec
    rts
.endproc

; A slot's names from the reply into identity_tiles, if they are the slot
; asked for and all characters the scope has. Carry set if not.
.proc radar_names
    lda NAMES_RECORD
    cmp radar_slot
    bne @bad
    ldy #IDENTITY_RECORD_SIZE - 1
@check:
    lda NAMES_RECORD,y
    jsr validate_identity_char  ; preserves Y
    bcs @bad
    dey
    bne @check
    lda radar_slot
    asl a
    asl a
    asl a                       ; slot * 8
    sta temp
    asl a                       ; slot * 16
    clc
    adc temp                    ; slot * 24
    tax
    ldy #1
@character:
    lda NAMES_RECORD,y
    jsr identity_char_tile      ; preserves X and Y
    sta identity_tiles,x
    inx
    iny
    cpy #IDENTITY_RECORD_SIZE
    bne @character
    clc
    rts
@bad:
    sec
    rts
.endproc

; The reply's scene to the screen, as nes-radar accepts a scene's packet:
; its records checked, the targets, the selected aircraft and the status
; made from them, and the four frames of it written.
.proc radar_take
    lda SCENE_FLAGS
    sta packet_flags
    and #$E0
    bne @bad
    lda SCENE_COUNT
    cmp #MAX_TARGETS + 1
    bcs @bad
    sta packet_count
    asl a
    asl a
    asl a                       ; count * 8
    clc
    adc packet_count            ; count * 9
    tax
    adc #SCENE_HEAD
    cmp nesp_reply_len
    bne @bad
    txa
    beq @checked
@record:
    lda SCENE_RECORDS - 1,x
    sta scene_payload - 1,x
    dex
    bne @record
    jsr validate_records
    bcs @bad
    lda seen_slots
@checked:
    sta active_slots
    lda SCENE_SERIAL
    sta radar_have
    lda packet_count
    sta displayed_count
    lda #0
    sta controller_pressed
    jsr move_selection          ; the selected aircraft may have gone
    jsr build_oam_shadow
    jsr build_selected_fields
    jsr build_status_fields     ; and the link is LIVE
    lda packet_flags
    and #SCENE_STALE
    beq :+
    jsr set_link_waiting
:
    lda packet_flags
    and #SCENE_SEVERE
    beq :+
    jsr set_link_adsb_down
:
    jsr note_link_stream        ; and if it is still LIVE, a new scene has come
    jmp commit_display

    ; The records are where the last scene's were, so nothing of that can
    ; stay on the scope.
@bad:
    jsr clear_target_state
    lda #<link_bad_data_chars   ; an aircraft or a name that cannot be shown
    ldx #>link_bad_data_chars
    jsr show_link
    jmp commit_display
.endproc

.ifdef CART
; On nesp32's cartridge the ROM's two pages of tiles are among the others'
; on an MMC1, where the build says (cart.inc: CART_CHR, as the mapper
; counts them, in halves of a page). A = the page of its own that it
; wants, 0 or 1. The mapper's register is written a bit at a time, five
; writes; the menu left the mapper with none begun.
.include "cart.inc"
MMC1_CHR0 = $A000

.proc radar_cart_chr
    asl a
    clc
    adc #CART_CHR
    ldx #5
:
    sta MMC1_CHR0
    lsr a
    dex
    bne :-
    rts
.endproc
.endif

; The editor's message for startup_error: why there was no scope.
.proc radar_show_error
    lda startup_error
    cmp #OPEN_SILENT
    bcs :+
    jmp show_startup_message    ; nes-radar's own: INVALID AIRPORT
:
    sbc #OPEN_SILENT            ; carry is set
    asl a
    asl a
    asl a
    asl a
    clc
    adc #<radar_messages
    sta field_src
    lda #>radar_messages
    adc #0
    sta field_src + 1
    lda #FONT_DIM_BASE
    sta field_font
    jsr begin_vram_update
    ldy #16
    lda #>STARTUP_MESSAGE_ADDR
    ldx #<STARTUP_MESSAGE_ADDR
    jsr write_field
    jmp restore_scroll
.endproc
