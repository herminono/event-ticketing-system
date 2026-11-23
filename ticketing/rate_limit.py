from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

def verified_user_key():
    verify_jwt_in_request()
    user_id = get_jwt_identity()
    return f"user:{user_id}"