<!-- viewproduct.php (POS component) -->
<?php
include_once 'connectdb.php';
session_start();
include_once "header.php";
include 'barcode/barcode128.php';
?>

<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
    <!-- Content Header (Page header) -->
    <div class="content-header">
        <div class="container-fluid">
            <div class="row mb-2">
                <div class="col-sm-6">
                    <!-- <h1 class="m-0">Admin Dashboard</h1> -->
                </div><!-- /.col -->
                <div class="col-sm-6">
                    <ol class="breadcrumb float-sm-right">
                        <!-- Breadcrumb items, if any -->
                    </ol>
                </div><!-- /.col -->
            </div><!-- /.row -->
        </div><!-- /.container-fluid -->
    </div>
    <!-- /.content-header -->

    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="row">
                <div class="col-lg-12">
                    <div class="card card-info card-outline">
                        <div class="card-header">
                            <h5 class="m-0">View Product</h5>
                        </div>
                        <div class="card-body">
                            <?php
                            // Get the product id from the URL (e.g., viewproduct.php?id=1)
                            $id = $_GET['id'];

                            // Query the products table joined with categories to retrieve the category name
                            $select = $pdo->prepare("SELECT p.*, c.category_name 
                                                     FROM products p 
                                                     JOIN categories c ON p.category_id = c.category_id 
                                                     WHERE p.product_id = :id");
                            $select->bindParam(':id', $id, PDO::PARAM_INT);
                            $select->execute();

                            while ($row = $select->fetch(PDO::FETCH_OBJ)) {
                                echo '
                                <div class="row">
                                    <div class="col-md-6">
                                        <ul class="list-group">
                                            <center><p class="list-group-item list-group-item-info"><b>PRODUCT DETAILS</b></p></center>
                                            <li class="list-group-item">
                                                <b>Barcode</b>
                                                <span class="badge badge-light float-right">' . bar128($row->barcode) . '</span>
                                            </li>
                                            <li class="list-group-item">
                                                <b>Product Name</b>
                                                <span class="badge badge-warning float-right">' . $row->product_name . '</span>
                                            </li>
                                            <li class="list-group-item">
                                                <b>Category</b>
                                                <span class="badge badge-primary float-right">' . $row->category_name . '</span>
                                            </li>
                                            <li class="list-group-item">
                                                <b>Description</b>
                                                <span class="badge badge-success float-right">' . $row->description . '</span>
                                            </li>
                                            <li class="list-group-item">
                                                <b>Stock</b>
                                                <span class="badge badge-danger float-right">' . $row->stock . '</span>
                                            </li>
                                            <li class="list-group-item">
                                                <b>Purchase Price</b>
                                                <span class="badge badge-secondary float-right">' . $row->purchase_price . '</span>
                                            </li>
                                            <li class="list-group-item">
                                                <b>Sale Price</b>
                                                <span class="badge badge-dark float-right">' . $row->sale_price . '</span>
                                            </li>
                                            <li class="list-group-item">
                                                <b>Product Profit</b>
                                                <span class="badge badge-success float-right">' . ($row->sale_price - $row->purchase_price) . '</span>
                                            </li>
                                        </ul>
                                    </div>
                                    <div class="col-md-6">
                                        <ul class="list-group">
                                            <center><p class="list-group-item list-group-item-info"><b>PRODUCT IMAGE</b></p></center>
                                            <img src="productimages/' . $row->image . '" class="img-responsive"/>
                                        </ul>
                                    </div>
                                </div>
                                ';
                            }
                            ?>
                        </div><!-- /.card-body -->
                    </div><!-- /.card -->
                </div><!-- /.col-lg-12 -->
            </div><!-- /.row -->
        </div><!-- /.container-fluid -->
    </div><!-- /.content -->
</div><!-- /.content-wrapper -->

<?php
include_once "footer.php";
?>
