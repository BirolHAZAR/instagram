from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    SUPPRESSED_MESSAGE_TEMPLATES = {
        "account/messages/logged_in.txt",
        "account/messages/logged_out.txt",
    }

    def add_message(
        self,
        request,
        level,
        message_template=None,
        message_context=None,
        extra_tags="",
        message=None,
    ):
        if message_template in self.SUPPRESSED_MESSAGE_TEMPLATES:
            return
        return super().add_message(
            request,
            level,
            message_template=message_template,
            message_context=message_context,
            extra_tags=extra_tags,
            message=message,
        )
