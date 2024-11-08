from allure_behave.hooks import allure_report


def before_all(context):
    import steps

    allure_report(".allure")
