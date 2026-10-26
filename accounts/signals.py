from .utils import (
    generate_student_credentials,
    generate_lecturer_credentials,
    send_new_account_email,
)


def post_save_account_receiver(instance=None, created=False, *args, **kwargs):
    """Handle generated credentials unless a managed form supplied them."""
    if not created:
        return

    if getattr(instance, "_preserve_supplied_credentials", False):
        supplied_password = getattr(instance, "_supplied_password", None)
        if supplied_password and getattr(instance, "email", ""):
            send_new_account_email(instance, supplied_password)
        return

    if instance.is_student:
        username, password = generate_student_credentials()
        instance.username = username
        instance.set_password(password)
        instance.save()
        send_new_account_email(instance, password)

    elif instance.is_lecturer:
        username, password = generate_lecturer_credentials()
        instance.username = username
        instance.set_password(password)
        instance.save()
        send_new_account_email(instance, password)
